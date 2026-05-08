"""Persistent Chroma vector store helpers."""

from __future__ import annotations

from pathlib import Path
from typing import List

from langchain_chroma import Chroma
from langchain_core.documents import Document

from src.core.embeddings import get_embeddings


def get_or_create_vectordb(
    chunks: List[Document],
    persist_path: Path,
    collection_name: str,
) -> Chroma:
    """
    Load an existing Chroma collection if non-empty, otherwise create one
    from ``chunks`` and persist it to disk.

    Uses a single Chroma client throughout (the original pattern in
    Audit_Compliance.py instantiated the client twice, leaking the first one).
    """
    persist_path.mkdir(parents=True, exist_ok=True)

    embeddings = get_embeddings()

    vectordb = Chroma(
        collection_name=collection_name,
        embedding_function=embeddings,
        persist_directory=str(persist_path),
    )

    if vectordb._collection.count() == 0:
        if not chunks:
            raise ValueError(
                "Vector DB is empty and no chunks were provided to populate it."
            )
        # ChromaDB caps a single add_documents call at ~5 000 items.
        # Batch to stay well under the limit.
        _BATCH = 4000
        for i in range(0, len(chunks), _BATCH):
            vectordb.add_documents(chunks[i : i + _BATCH])

    return vectordb
