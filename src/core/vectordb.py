"""Persistent Chroma vector store helpers."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Dict, List

import chromadb
from chromadb.api.shared_system_client import SharedSystemClient
from langchain_chroma import Chroma
from langchain_core.documents import Document

from src.core.embeddings import get_embeddings


# Streamlit re-runs recreate LangChain Chroma wrappers frequently. Chroma's
# SharedSystemClient + RustBindingsAPI on Python 3.14 can end up with a
# stopped system whose ``bindings`` attribute was deleted, which then surfaces
# as AttributeError / "Could not connect to tenant default_tenant".
# Cache one PersistentClient per persist directory for the process lifetime.
_CLIENTS: Dict[str, chromadb.ClientAPI] = {}
_CLIENTS_LOCK = threading.Lock()


def _is_chroma_bindings_error(exc: BaseException) -> bool:
    msg = str(exc).lower()
    return (
        "bindings" in msg
        or "default_tenant" in msg
        or "could not connect to tenant" in msg
    )


def get_persistent_client(persist_path: Path) -> chromadb.ClientAPI:
    """Return a process-cached PersistentClient for ``persist_path``."""
    persist_path.mkdir(parents=True, exist_ok=True)
    key = str(persist_path.resolve())

    with _CLIENTS_LOCK:
        client = _CLIENTS.get(key)
        if client is not None:
            return client

        try:
            client = chromadb.PersistentClient(path=key)
        except Exception as exc:  # noqa: BLE001
            if not _is_chroma_bindings_error(exc):
                raise
            # Drop any half-stopped SharedSystemClient entry and retry once.
            SharedSystemClient.clear_system_cache()
            _CLIENTS.clear()
            client = chromadb.PersistentClient(path=key)

        _CLIENTS[key] = client
        return client


def get_or_create_vectordb(
    chunks: List[Document],
    persist_path: Path,
    collection_name: str,
) -> Chroma:
    """
    Load an existing Chroma collection if non-empty, otherwise create one
    from ``chunks`` and persist it to disk.

    Uses a single cached Chroma client per persist directory so Streamlit
    reruns do not tear down Rust bindings mid-session.
    """
    embeddings = get_embeddings()
    client = get_persistent_client(persist_path)

    try:
        vectordb = Chroma(
            client=client,
            collection_name=collection_name,
            embedding_function=embeddings,
        )
    except Exception as exc:  # noqa: BLE001
        if not _is_chroma_bindings_error(exc):
            raise
        with _CLIENTS_LOCK:
            SharedSystemClient.clear_system_cache()
            _CLIENTS.clear()
        client = get_persistent_client(persist_path)
        vectordb = Chroma(
            client=client,
            collection_name=collection_name,
            embedding_function=embeddings,
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
