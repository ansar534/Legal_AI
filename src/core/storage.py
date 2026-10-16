"""Uploaded files: bytes in Azure Blob Storage, a ledger row in PostgreSQL."""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Optional

from azure.storage.blob import ContainerClient, ContentSettings

from src.core.config import SCRATCH_DIR, get_required_env, load_env
from src.core.identity import get_credential
from src.core.loaders import sanitize_for_collection
from src.db.connection import get_pool


@dataclass(frozen=True)
class StoredUpload:
    filename: str
    blob_name: str
    sha256: str
    size_bytes: int
    # Copy for the PDF/TXT parsers. The blob is the durable original.
    local_path: Path


@lru_cache(maxsize=1)
def _container() -> ContainerClient:
    load_env()
    return ContainerClient(
        account_url=get_required_env("AZURE_STORAGE_ACCOUNT_URL"),
        container_name=os.getenv("AZURE_STORAGE_CONTAINER", "uploads"),
        credential=get_credential(),
    )


def store_upload(
    feature: str,
    filename: str,
    data: bytes,
    collection_name: str,
    content_type: Optional[str] = None,
) -> StoredUpload:
    """
    Write an uploaded file to the blob container and record it.

    Blobs are keyed by content hash, so re-uploading the same file is a
    no-op rather than a second copy.
    """
    sha = hashlib.sha256(data).hexdigest()
    name = Path(filename).name
    blob_name = f"{feature}/{sha[:16]}/{name}"
    content_type = content_type or "application/octet-stream"

    blob = _container().get_blob_client(blob_name)
    if not blob.exists():
        blob.upload_blob(
            data,
            content_settings=ContentSettings(content_type=content_type),
            metadata={"feature": feature, "sha256": sha},
        )

    with get_pool().connection() as conn:
        conn.execute(
            """
            INSERT INTO uploads
                (feature, filename, blob_name, content_type, size_bytes, sha256, collection_name)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (blob_name) DO NOTHING
            """,
            (feature, name, blob_name, content_type, len(data), sha, collection_name),
        )

    local_path = SCRATCH_DIR / "uploads" / sha[:16] / name
    if not local_path.exists():
        local_path.parent.mkdir(parents=True, exist_ok=True)
        local_path.write_bytes(data)

    return StoredUpload(name, blob_name, sha, len(data), local_path)


def upload_collection_name(filename: str, data: bytes) -> str:
    """Collection for one uploaded file; the hash keeps same-named files apart."""
    return f"upload_{sanitize_for_collection(filename)}_{hashlib.sha256(data).hexdigest()[:8]}"
