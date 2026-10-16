"""Reusable Streamlit UI widgets shared by every file-based feature."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, List, Optional

import streamlit as st

from src.core.schemas import DataSource
from src.core.storage import StoredUpload, store_upload, upload_collection_name

if TYPE_CHECKING:
    from src.features import FeatureSpec


def save_upload(feature_key: str, uploaded) -> tuple[StoredUpload, str]:
    """
    Store a Streamlit upload in Blob Storage once per session.

    Streamlit reruns the page on every interaction; without this the same
    file would be re-sent to the blob container each time.
    """
    data = uploaded.getvalue()
    collection = upload_collection_name(uploaded.name, data)
    cache: dict = st.session_state.setdefault("_stored_uploads", {})
    key = (feature_key, collection)
    stored = cache.get(key)
    if stored is None or not stored.local_path.exists():
        stored = store_upload(
            feature=feature_key,
            filename=uploaded.name,
            data=data,
            collection_name=collection,
            content_type=uploaded.type,
        )
        cache[key] = stored
    return stored, collection


def _list_existing(folder: Path, suffixes: List[str]) -> List[Path]:
    if not folder or not folder.exists():
        return []
    files: List[Path] = []
    for suffix in suffixes:
        files.extend(sorted(folder.glob(f"*.{suffix}")))
    return [f for f in files if f.is_file()]


def source_picker(spec: "FeatureSpec") -> Optional[DataSource]:
    """
    Render the "Use Existing" vs "Upload New" widget in the sidebar.

    Returns ``None`` when the user hasn't yet selected anything actionable
    (e.g. upload mode with no file uploaded). Pages should short-circuit
    on ``None`` and let the user keep interacting with the sidebar.
    """
    if not spec.data_folder:
        st.sidebar.info("This feature does not use local files.")
        return None

    spec.data_folder.mkdir(parents=True, exist_ok=True)

    st.sidebar.markdown(f"### {spec.title}")
    if spec.description:
        st.sidebar.caption(spec.description)

    mode = st.sidebar.radio(
        "Document source",
        ("Use existing documents", "Upload new file"),
        key=f"{spec.key}__mode",
    )

    suffixes = spec.supported_uploads or ["pdf"]

    if mode == "Use existing documents":
        existing = _list_existing(spec.data_folder, suffixes)

        if not existing:
            st.sidebar.warning(
                f"No files found in `{spec.data_folder}`. Upload one instead."
            )
            return None

        choice = st.sidebar.multiselect(
            "Select documents (leave empty to use ALL)",
            options=[p.name for p in existing],
            default=[],
            key=f"{spec.key}__existing",
        )

        files = (
            [p for p in existing if p.name in set(choice)]
            if choice
            else existing
        )

        return DataSource(
            files=files,
            collection_name=spec.default_collection,
            is_upload=False,
            label=(
                f"Existing ({len(files)} of {len(existing)})"
                if choice
                else f"Existing (all {len(existing)})"
            ),
        )

    uploaded = st.sidebar.file_uploader(
        "Upload a file",
        type=suffixes,
        accept_multiple_files=False,
        key=f"{spec.key}__upload",
    )

    if uploaded is None:
        st.sidebar.info("Awaiting upload...")
        return None

    try:
        stored, collection = save_upload(spec.key, uploaded)
    except Exception as exc:  # noqa: BLE001
        st.sidebar.error(f"Could not store the upload: {exc}")
        return None

    st.sidebar.success(f"Stored in Blob Storage: `{stored.blob_name}`")

    return DataSource(
        files=[stored.local_path],
        collection_name=collection,
        is_upload=True,
        label=f"Upload: {stored.filename}",
    )
