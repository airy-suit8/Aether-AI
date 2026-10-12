"""
chunking/chunker.py — split loaded Documents into overlapping chunks (Task 13).

One splitter for every upload: LangChain's RecursiveCharacterTextSplitter with the chunk size
and overlap from settings. Each chunk keeps its source, page and type, and gets a unique id and
its position in the document.
"""

import uuid
from typing import List

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from src.core.config import settings


def split_documents(raw_docs: List[Document]) -> List[Document]:
    """Split into chunks of at most settings.chunk_size characters, overlapping by settings.chunk_overlap."""
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=settings.chunk_size,
        chunk_overlap=settings.chunk_overlap,
        separators=["\n\n", "\n", ". ", " ", ""],
    )
    chunks = splitter.split_documents(raw_docs)

    total = len(chunks)
    for i, chunk in enumerate(chunks):
        chunk.metadata["chunk_id"] = str(uuid.uuid4())
        chunk.metadata["chunk_index"] = i + 1
        chunk.metadata["total_chunks"] = total
    return chunks
