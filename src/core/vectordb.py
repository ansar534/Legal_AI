"""Vector store backed by pgvector on the managed PostgreSQL server."""

from __future__ import annotations

import hashlib
import uuid
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, NamedTuple, Optional, Sequence, Set, Tuple

import numpy as np
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_core.vectorstores import VectorStore
from langchain_core.vectorstores.utils import maximal_marginal_relevance
from psycopg.types.json import Jsonb

from src.core import loaders
from src.core.embeddings import DEFAULT_EMBEDDING_MODEL, get_embeddings
from src.db.connection import get_pool


EMBEDDING_DIM = 384
_INSERT_BATCH = 256

_INSERT_SQL = """
    INSERT INTO chunks (collection_id, chunk_id, filename, page, content, metadata, embedding)
    VALUES (%s, %s, %s, %s, %s, %s, %s)
    ON CONFLICT (collection_id, chunk_id) DO NOTHING
"""


def clean_text(value: str) -> str:
    """PostgreSQL text and jsonb reject NUL bytes, which some PDFs contain."""
    return value.replace("\x00", "")


def clean_metadata(metadata: Dict[str, Any]) -> Dict[str, Any]:
    return {
        k: clean_text(v) if isinstance(v, str) else v
        for k, v in metadata.items()
    }


def chunk_row(
    collection_id: int,
    chunk_id: str,
    content: str,
    metadata: Dict[str, Any],
    embedding: Sequence[float],
) -> tuple:
    """One `chunks` row, shared by the app and the Chroma import tool."""
    metadata = clean_metadata(metadata)
    vector = np.asarray(embedding, dtype=np.float32)
    if vector.shape != (EMBEDDING_DIM,):
        raise ValueError(f"Expected a {EMBEDDING_DIM}-d embedding, got {vector.shape}")
    page = metadata.get("page")
    return (
        collection_id,
        chunk_id,
        metadata.get("filename") or "unknown",
        page if isinstance(page, int) else None,
        clean_text(content),
        Jsonb(metadata),
        vector,
    )


def ensure_collection(name: str, embedding_model: str = DEFAULT_EMBEDDING_MODEL) -> int:
    """Return the id of collection ``name``, creating it if needed."""
    with get_pool().connection() as conn:
        row = conn.execute(
            """
            INSERT INTO collections (name, embedding_model) VALUES (%s, %s)
            ON CONFLICT (name) DO UPDATE SET name = EXCLUDED.name
            RETURNING id
            """,
            (name, embedding_model),
        ).fetchone()
    return row[0]


def _filename_scope(filter: Optional[dict]) -> Optional[List[str]]:
    """Translate the retriever filter ``{"filename": {"$in": [...]}}``."""
    if not filter:
        return None
    unknown = set(filter) - {"filename"}
    if unknown:
        raise ValueError(f"Unsupported filter keys: {sorted(unknown)}")
    cond = filter["filename"]
    if isinstance(cond, str):
        return [cond]
    if isinstance(cond, dict) and set(cond) == {"$in"}:
        return list(cond["$in"])
    raise ValueError(f"Unsupported filename filter: {cond!r}")


def _as_array(value: Any) -> np.ndarray:
    """pgvector >= 0.4 loads `vector` columns as a Vector object, not an ndarray."""
    if hasattr(value, "to_numpy"):
        value = value.to_numpy()
    return np.asarray(value, dtype=np.float32)


class _Hit(NamedTuple):
    document: Document
    distance: float
    embedding: Optional[np.ndarray]


@lru_cache(maxsize=4)
def _load_documents(
    collection_id: int,
    filenames: Optional[Tuple[str, ...]],
    row_count: int,
) -> Tuple[Document, ...]:
    # row_count is part of the key so the cache drops out once a file is added.
    sql = "SELECT chunk_id, content, metadata FROM chunks WHERE collection_id = %s"
    params: List[Any] = [collection_id]
    if filenames:
        sql += " AND filename = ANY(%s)"
        params.append(list(filenames))
    sql += " ORDER BY filename, page NULLS FIRST, chunk_id"
    with get_pool().connection() as conn:
        rows = conn.execute(sql, params).fetchall()
    return tuple(
        Document(id=chunk_id, page_content=content, metadata=metadata)
        for chunk_id, content, metadata in rows
    )


class PgVectorStore(VectorStore):
    """One collection's chunks in the `chunks` table, searched by cosine distance."""

    def __init__(self, collection_name: str, embeddings: Optional[Embeddings] = None):
        self.collection_name = collection_name
        self._embeddings = embeddings or get_embeddings()
        self.collection_id = ensure_collection(collection_name)

    @property
    def embeddings(self) -> Embeddings:
        return self._embeddings

    # ------------------------------------------------------------------ reads

    def count(self) -> int:
        with get_pool().connection() as conn:
            return conn.execute(
                "SELECT count(*) FROM chunks WHERE collection_id = %s",
                (self.collection_id,),
            ).fetchone()[0]

    def indexed_filenames(self) -> Set[str]:
        with get_pool().connection() as conn:
            rows = conn.execute(
                "SELECT DISTINCT filename FROM chunks WHERE collection_id = %s",
                (self.collection_id,),
            ).fetchall()
        return {r[0] for r in rows}

    def get_documents(self, filenames: Optional[Sequence[str]] = None) -> List[Document]:
        """Stored chunks, optionally limited to ``filenames``; feeds BM25."""
        key = tuple(sorted(set(filenames))) if filenames else None
        return list(_load_documents(self.collection_id, key, self.count()))

    def _search(
        self,
        embedding: Sequence[float],
        k: int,
        filenames: Optional[List[str]],
        with_embeddings: bool = False,
    ) -> List[_Hit]:
        query = np.asarray(embedding, dtype=np.float32)
        columns = "chunk_id, content, metadata, embedding <=> %(q)s AS distance"
        if with_embeddings:
            columns += ", embedding"
        sql = f"SELECT {columns} FROM chunks WHERE collection_id = %(cid)s"
        if filenames:
            sql += " AND filename = ANY(%(files)s)"
        sql += " ORDER BY embedding <=> %(q)s LIMIT %(k)s"
        params = {"q": query, "cid": self.collection_id, "files": filenames, "k": k}
        with get_pool().connection() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [
            _Hit(
                Document(id=row[0], page_content=row[1], metadata=row[2]),
                float(row[3]),
                _as_array(row[4]) if with_embeddings else None,
            )
            for row in rows
        ]

    def similarity_search_with_score(
        self, query: str, k: int = 4, filter: Optional[dict] = None, **kwargs: Any
    ) -> List[Tuple[Document, float]]:
        hits = self._search(self._embeddings.embed_query(query), k, _filename_scope(filter))
        return [(h.document, h.distance) for h in hits]

    def similarity_search(
        self, query: str, k: int = 4, filter: Optional[dict] = None, **kwargs: Any
    ) -> List[Document]:
        return [doc for doc, _ in self.similarity_search_with_score(query, k, filter)]

    def similarity_search_by_vector(
        self, embedding: List[float], k: int = 4, filter: Optional[dict] = None, **kwargs: Any
    ) -> List[Document]:
        return [h.document for h in self._search(embedding, k, _filename_scope(filter))]

    def max_marginal_relevance_search(
        self,
        query: str,
        k: int = 4,
        fetch_k: int = 20,
        lambda_mult: float = 0.5,
        filter: Optional[dict] = None,
        **kwargs: Any,
    ) -> List[Document]:
        return self.max_marginal_relevance_search_by_vector(
            self._embeddings.embed_query(query), k, fetch_k, lambda_mult, filter
        )

    def max_marginal_relevance_search_by_vector(
        self,
        embedding: List[float],
        k: int = 4,
        fetch_k: int = 20,
        lambda_mult: float = 0.5,
        filter: Optional[dict] = None,
        **kwargs: Any,
    ) -> List[Document]:
        hits = self._search(embedding, fetch_k, _filename_scope(filter), with_embeddings=True)
        if not hits:
            return []
        picked = maximal_marginal_relevance(
            np.asarray(embedding, dtype=np.float32),
            [h.embedding for h in hits],
            lambda_mult=lambda_mult,
            k=k,
        )
        return [hits[i].document for i in picked]

    def _select_relevance_score_fn(self) -> Callable[[float], float]:
        return lambda distance: 1.0 - distance

    # ----------------------------------------------------------------- writes

    def add_texts(
        self,
        texts: Iterable[str],
        metadatas: Optional[List[dict]] = None,
        *,
        ids: Optional[List[str]] = None,
        **kwargs: Any,
    ) -> List[str]:
        texts = list(texts)
        metadatas = list(metadatas) if metadatas else [{} for _ in texts]
        ids = list(ids) if ids else [uuid.uuid4().hex for _ in texts]
        for start in range(0, len(texts), _INSERT_BATCH):
            stop = start + _INSERT_BATCH
            batch = [clean_text(t) for t in texts[start:stop]]
            vectors = self._embeddings.embed_documents(batch)
            rows = [
                chunk_row(self.collection_id, cid, text, meta, vec)
                for cid, text, meta, vec in zip(ids[start:stop], batch, metadatas[start:stop], vectors)
            ]
            with get_pool().connection() as conn, conn.cursor() as cur:
                cur.executemany(_INSERT_SQL, rows)
        return ids

    @classmethod
    def from_texts(
        cls,
        texts: List[str],
        embedding: Embeddings,
        metadatas: Optional[List[dict]] = None,
        *,
        ids: Optional[List[str]] = None,
        collection_name: str = "default",
        **kwargs: Any,
    ) -> "PgVectorStore":
        store = cls(collection_name, embedding)
        store.add_texts(texts, metadatas, ids=ids)
        return store


def _chunk_ids(chunks: Sequence[Document]) -> List[str]:
    """Stable ids, so indexing the same file twice inserts nothing new."""
    seen: Dict[str, int] = {}
    ids: List[str] = []
    for chunk in chunks:
        name = chunk.metadata.get("filename", "")
        ordinal = seen.get(name, 0)
        seen[name] = ordinal + 1
        key = f"{name}\0{ordinal}\0{chunk.page_content}".encode("utf-8", "ignore")
        ids.append(hashlib.sha256(key).hexdigest()[:32])
    return ids


def index_files(
    collection_name: str,
    files: Sequence[Path],
    split: Callable[[List[Document]], List[Document]],
    *,
    prepare: Optional[Callable[[Document], None]] = None,
    on_progress: Optional[Callable[[str], None]] = None,
) -> Tuple[PgVectorStore, List[Document]]:
    """
    Make sure every file is in the collection, then return its chunks.

    Files already in the database are not read, split, or embedded again;
    only new ones are. The returned chunks are read back from the database.
    """
    report = on_progress or (lambda _msg: None)
    store = PgVectorStore(collection_name)
    have = store.indexed_filenames()
    missing = [f for f in files if f.name not in have]
    if missing:
        report(f"Indexing {len(missing)} new file(s)...")
        docs = loaders.load_files_dispatch(list(missing))
        if prepare:
            for doc in docs:
                prepare(doc)
        chunks = split(docs)
        report(f"Embedding {len(chunks)} chunks...")
        store.add_documents(chunks, ids=_chunk_ids(chunks))
    chunks = store.get_documents([f.name for f in files])
    report(f"{len(chunks)} chunks ready in `{collection_name}`.")
    return store, chunks
