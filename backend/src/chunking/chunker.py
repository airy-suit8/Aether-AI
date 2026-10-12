"""
chunking/chunker.py — split loaded Documents into overlapping chunks (Task 13).

LangChain's RecursiveCharacterTextSplitter with the chunk size and overlap from settings. Prose
is cut at paragraphs, then lines, then sentences. Tables (CSV and Excel, one row per line) are
cut at rows, and a row wider than a chunk at the commas between its fields, never inside a
"Column: value" (R9). Each chunk keeps its source, page and type, and gets a unique id and its
position in the document.
"""

import uuid
from typing import List

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from src.core.config import settings

PROSE_SEPARATORS = ["\n\n", "\n", ". ", " ", ""]
TABLE_SEPARATORS = ["\n", ", ", " ", ""]
TABLE_TYPES = ("csv", "xlsx", "xls")


def split_documents(raw_docs: List[Document]) -> List[Document]:
    """Split into chunks of at most settings.chunk_size characters, overlapping by settings.chunk_overlap."""
    chunks = []
    for doc in raw_docs:
        is_table = doc.metadata.get("type") in TABLE_TYPES
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=settings.chunk_size,
            chunk_overlap=settings.chunk_overlap,
            separators=TABLE_SEPARATORS if is_table else PROSE_SEPARATORS,
        )
        pieces = splitter.split_documents([doc])
        if is_table:
            for piece in pieces:  # a row cut at ", " keeps that comma at the start of the next piece
                piece.page_content = piece.page_content.strip(", ")
        chunks.extend(pieces)

    total = len(chunks)
    for i, chunk in enumerate(chunks):
        chunk.metadata["chunk_id"] = str(uuid.uuid4())
        chunk.metadata["chunk_index"] = i + 1
        chunk.metadata["total_chunks"] = total
    return chunks
