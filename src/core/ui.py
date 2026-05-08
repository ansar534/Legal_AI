"""Reusable Streamlit UI widgets shared by every file-based feature."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, List, Optional

import streamlit as st

from src.core.config import UPLOAD_CHROMA_ROOT
from src.core.loaders import sanitize_for_collection, save_uploaded_file
from src.core.schemas import DataSource

if TYPE_CHECKING:
    from src.features import FeatureSpec


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
            persist_path=spec.collection_path,
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

    upload_dir = spec.data_folder / "uploads"
    saved_path = save_uploaded_file(uploaded, upload_dir)

    sanitized = sanitize_for_collection(saved_path.name)
    collection = f"upload_{sanitized}"
    persist_path = UPLOAD_CHROMA_ROOT / sanitized

    st.sidebar.success(f"Uploaded: {saved_path.name}")

    return DataSource(
        files=[saved_path],
        collection_name=collection,
        persist_path=persist_path,
        is_upload=True,
        label=f"Upload: {saved_path.name}",
    )
