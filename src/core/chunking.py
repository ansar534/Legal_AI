"""Single replacement for the various split_documents/chunk_docs copies."""

from __future__ import annotations

from typing import List, Optional, Sequence

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter


DEFAULT_SEPARATORS: Sequence[str] = ("\n\n", "\n", ". ", " ", "")


def split_documents(
    docs: List[Document],
    chunk_size: int = 1000,
    chunk_overlap: int = 200,
    separators: Optional[Sequence[str]] = None,
) -> List[Document]:
    """Recursively split documents and drop empty chunks."""
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=list(separators or DEFAULT_SEPARATORS),
    )
    chunks = splitter.split_documents(docs)
    return [c for c in chunks if c.page_content.strip()]
