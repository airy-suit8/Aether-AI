"""
ingestion/loader.py — read an uploaded file into LangChain Documents, one per page or block.

Two loaders sit behind one interface, load_document(), chosen by settings.document_loader:
  native     (default) pypdf, python-docx and pandas parsers written for this app
  langchain  Task 12: LangChain's document loaders (PyPDFLoader, Docx2txtLoader, TextLoader,
             CSVLoader); Excel files use the native pandas parser in both

Both give metadata {"source", "page", "type"} with pages numbered from 1. A file that cannot
be read raises DocumentError, whose message is safe to show the person who uploaded it.

The native PDF parser reads a page with no text (a scan, a photo) by OCR (ingestion/ocr.py, when
settings.ocr is on), and marks it {"ocr": True}.
"""

import codecs
import io
import math
import os
import re
import unicodedata
import zipfile
from datetime import datetime, time
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
from docx import Document as DocxDoc
from docx.table import Table
from langchain_community.document_loaders import CSVLoader, Docx2txtLoader, PyPDFLoader, TextLoader
from langchain_core.documents import Document
from pypdf import PdfReader

from src.core.config import settings
from src.ingestion import ocr

SUPPORTED_EXTENSIONS = (".pdf", ".txt", ".md", ".markdown", ".docx", ".csv", ".xlsx", ".xls")

# Rows of a table grouped into one Document, to keep chunk sizes manageable
ROWS_PER_DOCUMENT = 50


class DocumentError(ValueError):
    """An upload that cannot be read. The message names no server path and is shown to the user."""


FILENAME_MAX_CHARS = 150
# Not allowed in a Windows file name, and "<", ">" and quotes would read as markup in the prompt
_FILENAME_FORBIDDEN = re.compile(r'[<>:"/\\|?*]')


def clean_filename(name: str) -> str:
    """
    An uploaded file's name as the app stores, lists and quotes it (S5): the last part of any
    path, without control or invisible formatting characters (a right-to-left override can make
    "txt.exe" display as "exe.txt"), characters a Windows name cannot hold replaced by "_",
    spaces collapsed, at most FILENAME_MAX_CHARS long with its extension kept.
    """
    name = re.split(r"[/\\]", name or "")[-1]
    name = "".join(c for c in name if unicodedata.category(c) not in ("Cc", "Cf"))
    name = " ".join(_FILENAME_FORBIDDEN.sub("_", name).split()).rstrip(".")  # Windows drops a trailing dot
    stem, ext = os.path.splitext(name)
    if len(name) > FILENAME_MAX_CHARS:
        ext = ext[:16]
        name = stem[:FILENAME_MAX_CHARS - len(ext)].rstrip() + ext
    return name if os.path.splitext(name)[0] else "document" + ext


# ── Native parsers ────────────────────────────────────────────────────────────

def _parse_pdf(file_path: str, filename: str, owner: Optional[str] = None) -> List[Document]:
    """Extract text page-by-page using pypdf (pure Python); a page with none, a picture of text,
    is read by OCR, counted against the owner's hourly limit when an owner is given."""
    reader = PdfReader(file_path)
    texts = {number: (page.extract_text() or "").strip() for number, page in enumerate(reader.pages, start=1)}
    pictures = [number for number, text in texts.items() if not text]
    by_ocr = set()
    if pictures and settings.ocr:
        if len(pictures) > settings.ocr_max_pages:
            raise DocumentError(
                f"'{filename}' has {len(pictures)} pages that are pictures of text, and at most "
                f"{settings.ocr_max_pages} are read by OCR in one file. Split it into smaller files and upload those.")
        try:
            found = ocr.read_pages(file_path, pictures, owner)
        except ocr.OcrLimitReached as limit:
            raise DocumentError(
                f"'{filename}' has {limit.asked} pages that are pictures of text, and you have had {limit.used} "
                f"read by OCR in the last hour, of {limit.limit} an hour. Upload it again later.") from None
        except Exception as e:
            raise DocumentError(f"'{filename}' has pages that are pictures of text, and OCR could not read them "
                                "on this server. Upload a text version.") from e
        for number, text in found.items():
            if text.strip():
                texts[number] = text.strip()
                by_ocr.add(number)
    docs = [
        Document(page_content=text,
                 metadata={"source": filename, "page": number, "type": "pdf", **({"ocr": True} if number in by_ocr else {})})
        for number, text in texts.items() if text
    ]
    if not docs and len(reader.pages):
        raise DocumentError(
            f"'{filename}' has no text to read: its pages look like scans or photos, and "
            + ("OCR found no words on them either. Upload a clearer scan, or a text version." if settings.ocr else
               "reading pictures of text (OCR) is turned off on this server. Upload a text version.")
        )
    return docs


def _block_lines(blocks) -> List[str]:
    """The text of paragraphs and tables, in the order they appear. A table row is 'cell | cell'."""
    lines = []
    for block in blocks:
        if isinstance(block, Table):
            for row in block.rows:
                cells = []
                for cell in row.cells:  # a merged cell is listed once per column it spans
                    text = " ".join(cell.text.split())
                    if text and (not cells or cells[-1] != text):
                        cells.append(text)
                if cells:
                    lines.append(" | ".join(cells))
        elif block.text.strip():
            lines.append(block.text.strip())
    return lines


def _parse_docx(file_path: str, filename: str) -> List[Document]:
    """Read a Word .docx: headers, then paragraphs and tables in document order, then footers (R9)."""
    doc = DocxDoc(file_path)
    headers, footers = [], []
    for section in doc.sections:
        # A section linked to the previous one repeats its header and footer: keep each line once
        headers += [line for line in _block_lines(section.header.iter_inner_content()) if line not in headers]
        footers += [line for line in _block_lines(section.footer.iter_inner_content()) if line not in footers]
    lines = headers + _block_lines(doc.iter_inner_content()) + footers
    if not lines:
        return []
    return [Document(
        page_content="\n".join(lines),
        metadata={"source": filename, "page": 1, "type": "docx"},
    )]


def _decode(file_path: str, filename: str) -> str:
    """The file as text: UTF-8, or UTF-16 when it starts with a byte-order mark.

    Anything else is refused, not guessed. Reading with errors="ignore" dropped characters
    silently (R9), and a detector is no better on short files: charset-normalizer 3.4 read
    'Le café est fermé.' saved as Windows-1252 as UTF-16 Chinese characters.
    """
    data = Path(file_path).read_bytes()
    encoding = "utf-16" if data.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)) else "utf-8-sig"
    try:
        # Windows line endings read as plain newlines, as open() in text mode gives
        return data.decode(encoding).replace("\r\n", "\n").replace("\r", "\n")
    except UnicodeDecodeError as e:
        raise DocumentError(
            f"'{filename}' is not saved as UTF-8 text, so some of its characters cannot be read "
            "reliably. Save it again as UTF-8 (in Notepad: Save As, Encoding: UTF-8) and upload it."
        ) from e


def _parse_text(file_path: str, filename: str) -> List[Document]:
    """Read plain text or Markdown files."""
    text = _decode(file_path, filename).strip()
    if not text:
        return []
    return [Document(
        page_content=text,
        metadata={"source": filename, "page": 1, "type": "text"},
    )]


def _cell(value: Any) -> str:
    """A table cell as the text a person would read: no '5.0' for 5, no 'nan' for a blank."""
    if value is None or (isinstance(value, float) and math.isnan(value)) or value is pd.NaT:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if isinstance(value, datetime):  # a date cell arrives as midnight on that day
        return value.date().isoformat() if value.time() == time(0) else value.isoformat(sep=" ")
    return str(value).strip()


def _parse_tabular(file_path: str, filename: str, ext: str) -> List[Document]:
    """
    Read CSV or Excel and turn each row into a line, "Column1: val1, Column2: val2", which embeds
    better than bare values. Every sheet of a workbook is read; in a workbook with more than one,
    each Document starts with the sheet's name. Values are kept as written: codes keep their
    leading zeros and whole numbers stay whole (R9).
    """
    # One row more than the limit is read, to tell a file at the limit from one over it (S4)
    nrows = settings.max_table_rows + 1
    if ext == ".csv":
        # dtype=str: every value exactly as typed
        sheets: Dict[str, pd.DataFrame] = {"": pd.read_csv(
            io.StringIO(_decode(file_path, filename)), dtype=str, keep_default_na=False, nrows=nrows)}
    else:
        # dtype=object: text cells stay text ("007"); numbers arrive as numbers and _cell() prints them
        sheets = pd.read_excel(file_path, sheet_name=None, dtype=object, keep_default_na=False, nrows=nrows)
    if sum(len(df) for df in sheets.values()) > settings.max_table_rows:
        raise DocumentError(
            f"'{filename}' has more than {settings.max_table_rows:,} rows, the most one file may have. "
            "Split it into smaller files and upload those.")

    docs: List[Document] = []

    def flush(lines: List[str], sheet: str) -> None:
        title = [f"Sheet: {sheet}"] if len(sheets) > 1 else []
        docs.append(Document(
            page_content="\n".join(title + lines),
            metadata={"source": filename, "page": len(docs) + 1, "type": ext.lstrip(".")},
        ))

    for sheet, df in sheets.items():
        columns = [str(col) for col in df.columns]
        lines: List[str] = []
        for values in df.itertuples(index=False, name=None):
            cells = [(col, _cell(value)) for col, value in zip(columns, values)]
            line = ", ".join(f"{col}: {text}" for col, text in cells if text)
            if line:
                lines.append(line)
            if len(lines) >= ROWS_PER_DOCUMENT:
                flush(lines, sheet)
                lines = []
        if lines:
            flush(lines, sheet)

    return docs


def _unsupported(ext: str) -> DocumentError:
    return DocumentError(f"Unsupported file type '{ext}'. Allowed: pdf, docx, txt, md, csv, xlsx, xls")


def load_document_native(file_path: str, filename: str, owner: Optional[str] = None) -> List[Document]:
    """Dispatch to the correct parser based on file extension. owner: whose OCR limit a scan counts against."""
    ext = Path(filename).suffix.lower()
    if ext == ".pdf":
        return _parse_pdf(file_path, filename, owner)
    elif ext == ".docx":
        return _parse_docx(file_path, filename)
    elif ext in (".txt", ".md", ".markdown"):
        return _parse_text(file_path, filename)
    elif ext in (".csv", ".xlsx", ".xls"):
        return _parse_tabular(file_path, filename, ext)
    else:
        raise _unsupported(ext)


# ── LangChain loaders (Task 12) ───────────────────────────────────────────────

def load_document_langchain(file_path: str, filename: str) -> List[Document]:
    """
    Task 12: LangChain's document loaders, as an alternative to the native parsers.

    How they differ from the native parsers:
      PyPDFLoader     keeps a Document for a page with no text
      Docx2txtLoader  tables as tab-separated text, in its own order
      TextLoader      UTF-8 only (no UTF-16)
      CSVLoader       one Document per row
    """
    ext = Path(filename).suffix.lower()

    if ext == ".pdf":
        loader = PyPDFLoader(file_path)
    elif ext == ".docx":
        loader = Docx2txtLoader(file_path)
    elif ext in (".txt", ".md", ".markdown"):
        loader = TextLoader(file_path, encoding="utf-8")
    elif ext == ".csv":
        loader = CSVLoader(file_path)
    elif ext in (".xlsx", ".xls"):
        # pandas, as the native parser does, instead of UnstructuredExcelLoader (a 1GB+ dependency)
        return _parse_tabular(file_path, filename, ext)
    else:
        raise _unsupported(ext)

    # LangChain loaders return List[Document] with metadata already populated
    raw_docs = loader.load()

    # Normalize metadata to match our existing format
    for doc in raw_docs:
        doc.metadata["source"] = filename
        # PyPDFLoader numbers pages from 0; citations number them from 1, like the native parser
        doc.metadata["page"] = doc.metadata["page"] + 1 if "page" in doc.metadata else 1
        doc.metadata["type"] = ext.lstrip(".")

    return raw_docs


ZIP_FORMATS = (".docx", ".xlsx")


def _check_unpacked_size(file_path: str, filename: str) -> None:
    """Refuse a Word or Excel file (a zip archive) that would unpack to more than
    settings.max_unpacked_bytes, before a parser unpacks it (S4). The sizes are the ones the
    archive declares; the zip reader stops at them, so a file cannot unpack to more."""
    try:
        with zipfile.ZipFile(file_path) as archive:
            entries = archive.infolist()
    except zipfile.BadZipFile:
        return  # not a zip: the parser reports the file as unreadable
    if sum(entry.file_size for entry in entries) > settings.max_unpacked_bytes:
        raise DocumentError(
            f"'{filename}' unpacks to more than {settings.max_unpacked_bytes // (1024 * 1024)}MB, the most "
            "one file may hold. Split it into smaller files and upload those.")


def load_document(file_path: str, filename: str, owner: Optional[str] = None) -> List[Document]:
    """
    Load a file with the loader settings.document_loader names. owner: the uploader, whose hourly
    OCR limit a scanned PDF counts against (none: no limit, as for the evaluation's files).

    Raises DocumentError for a file that cannot be read. A parser's own error often quotes the
    server's temp path (R9), so it is kept as the cause, for the log, and replaced by a message
    that names only the user's file.
    """
    load = load_document_langchain if settings.document_loader == "langchain" else load_document_native
    try:
        if Path(filename).suffix.lower() in ZIP_FORMATS:
            _check_unpacked_size(file_path, filename)
        if load is load_document_native:
            return load_document_native(file_path, filename, owner)
        return load(file_path, filename)  # LangChain's loaders read no pictures, so no OCR limit applies
    except DocumentError:
        raise
    except Exception as e:
        kind = Path(filename).suffix.lower().lstrip(".") or "supported"
        raise DocumentError(
            f"'{filename}' could not be read. It may be damaged, password-protected, or not really a {kind} file."
        ) from e
