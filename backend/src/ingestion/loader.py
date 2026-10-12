"""
ingestion/loader.py — read an uploaded file into LangChain Documents, one per page or block.

Two loaders sit behind one interface, load_document(), chosen by settings.document_loader:
  native     (default) pypdf, python-docx and pandas parsers written for this app
  langchain  Task 12: LangChain's document loaders (PyPDFLoader, Docx2txtLoader, TextLoader,
             CSVLoader); Excel files use the native pandas parser in both

Both give metadata {"source", "page", "type"} with pages numbered from 1.
"""

from pathlib import Path
from typing import List

import pandas as pd
from docx import Document as DocxDoc
from langchain_community.document_loaders import CSVLoader, Docx2txtLoader, PyPDFLoader, TextLoader
from langchain_core.documents import Document
from pypdf import PdfReader

from src.core.config import settings

SUPPORTED_EXTENSIONS = (".pdf", ".txt", ".md", ".markdown", ".docx", ".csv", ".xlsx", ".xls")

# ── Native parsers ────────────────────────────────────────────────────────────

def _parse_pdf(file_path: str, filename: str) -> List[Document]:
    """Extract text page-by-page using pypdf (pure Python)."""
    docs = []
    reader = PdfReader(file_path)
    for page_num, page in enumerate(reader.pages, start=1):
        text = (page.extract_text() or "").strip()
        if text:
            docs.append(Document(
                page_content=text,
                metadata={"source": filename, "page": page_num, "type": "pdf"},
            ))
    return docs


def _parse_docx(file_path: str, filename: str) -> List[Document]:
    """Extract text from a Word .docx file using python-docx."""
    doc = DocxDoc(file_path)
    paragraphs = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
    if not paragraphs:
        return []
    text = "\n".join(paragraphs)
    return [Document(
        page_content=text,
        metadata={"source": filename, "page": 1, "type": "docx"},
    )]


def _parse_text(file_path: str, filename: str) -> List[Document]:
    """Read plain text or Markdown files."""
    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
        text = f.read().strip()
    if not text:
        return []
    return [Document(
        page_content=text,
        metadata={"source": filename, "page": 1, "type": "text"},
    )]


def _parse_tabular(file_path: str, filename: str, ext: str) -> List[Document]:
    """Read CSV or Excel and convert each row to a natural-language line for better embeddings."""
    if ext == ".csv":
        df = pd.read_csv(file_path)
    else:
        df = pd.read_excel(file_path)

    if df.empty:
        return []

    columns = list(df.columns)
    docs = []
    # Convert each row to a readable sentence: "Column1: val1, Column2: val2, ..."
    chunk_lines = []
    for idx, row in df.iterrows():
        line = ", ".join(f"{col}: {row[col]}" for col in columns if pd.notna(row[col]))
        chunk_lines.append(line)
        # Group every 50 rows into one Document to keep chunk sizes manageable
        if len(chunk_lines) >= 50:
            docs.append(Document(
                page_content="\n".join(chunk_lines),
                metadata={"source": filename, "page": len(docs) + 1, "type": ext.lstrip(".")},
            ))
            chunk_lines = []

    # Flush remaining rows
    if chunk_lines:
        docs.append(Document(
            page_content="\n".join(chunk_lines),
            metadata={"source": filename, "page": len(docs) + 1, "type": ext.lstrip(".")},
        ))

    return docs


def load_document_native(file_path: str, filename: str) -> List[Document]:
    """Dispatch to the correct parser based on file extension."""
    ext = Path(filename).suffix.lower()
    if ext == ".pdf":
        return _parse_pdf(file_path, filename)
    elif ext == ".docx":
        return _parse_docx(file_path, filename)
    elif ext in (".txt", ".md", ".markdown"):
        return _parse_text(file_path, filename)
    elif ext in (".csv", ".xlsx", ".xls"):
        return _parse_tabular(file_path, filename, ext)
    else:
        raise ValueError(f"Unsupported file type '{ext}'. Allowed: pdf, docx, txt, md, csv, xlsx, xls")


# ── LangChain loaders (Task 12) ───────────────────────────────────────────────

def load_document_langchain(file_path: str, filename: str) -> List[Document]:
    """
    Task 12: LangChain's document loaders, as an alternative to the native parsers.

    How they differ from the native parsers today:
      PyPDFLoader     keeps a Document for a page with no text
      Docx2txtLoader  reads tables, headers and footers too (the native parser drops them, R9)
      TextLoader      reads UTF-8 and raises on anything else (the native parser drops bytes)
      CSVLoader       one Document per row, values kept as text (no "5.0", no lost zeros)
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
        raise ValueError(f"Unsupported file type '{ext}'. Allowed: pdf, docx, txt, md, csv, xlsx, xls")

    # LangChain loaders return List[Document] with metadata already populated
    raw_docs = loader.load()

    # Normalize metadata to match our existing format
    for doc in raw_docs:
        doc.metadata["source"] = filename
        # PyPDFLoader numbers pages from 0; citations number them from 1, like the native parser
        doc.metadata["page"] = doc.metadata["page"] + 1 if "page" in doc.metadata else 1
        doc.metadata["type"] = ext.lstrip(".")

    return raw_docs


def load_document(file_path: str, filename: str) -> List[Document]:
    """Load a file with the loader settings.document_loader names."""
    if settings.document_loader == "langchain":
        return load_document_langchain(file_path, filename)
    return load_document_native(file_path, filename)
