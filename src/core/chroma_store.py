"""
On-disk Chroma vector store for local testing (``LEGAL_AI_LOCAL=1``).

Exposes the same surface ``vectordb.index_files`` and the retrievers use on
``PgVectorStore``, so pages run unchanged against the Milestone 3 stores in
``chromadb/``. chromadb is installed from requirements-local.txt only; the
production image never imports this module.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set

from langchain_chroma import Chroma
from langchain_core.documents import Document

from src.core.config import PROJECT_ROOT
from src.core.embeddings import get_embeddings


CHROMA_DIR = Path(os.getenv("CHROMA_DIR", PROJECT_ROOT / "chromadb"))
_PAGE_SIZE = 5000


class ChromaStore(Chroma):
    def __init__(self, collection_name: str):
        super().__init__(
            collection_name=collection_name,
            embedding_function=get_embeddings(),
            persist_directory=str(CHROMA_DIR),
        )

    def _get_all(self, include: List[str], where: Optional[dict] = None) -> Dict[str, list]:
        # One unpaged get() over a large collection exceeds SQLite's bound
        # variable limit ("too many SQL variables").
        out: Dict[str, list] = {"ids": [], **{k: [] for k in include}}
        offset = 0
        while True:
            page = self._collection.get(
                where=where, include=include, limit=_PAGE_SIZE, offset=offset
            )
            for key in out:
                out[key].extend(page[key])
            if len(page["ids"]) < _PAGE_SIZE:
                return out
            offset += _PAGE_SIZE

    def indexed_filenames(self) -> Set[str]:
        got = self._get_all(["metadatas"])
        return {m.get("filename") for m in got["metadatas"] if m and m.get("filename")}

    def get_documents(self, filenames: Optional[Sequence[str]] = None) -> List[Document]:
        where = {"filename": {"$in": list(filenames)}} if filenames else None
        got = self._get_all(["documents", "metadatas"], where)
        return [
            Document(id=cid, page_content=text or "", metadata=meta or {})
            for cid, text, meta in zip(got["ids"], got["documents"], got["metadatas"])
        ]
