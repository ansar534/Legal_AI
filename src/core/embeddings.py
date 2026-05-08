"""Cached embeddings singleton shared by every feature."""

from __future__ import annotations

from langchain_huggingface import HuggingFaceEmbeddings


DEFAULT_EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"


def _build_embeddings(model_name: str = DEFAULT_EMBEDDING_MODEL) -> HuggingFaceEmbeddings:
    return HuggingFaceEmbeddings(
        model_name=model_name,
        model_kwargs={"device": "cpu"},
        encode_kwargs={"normalize_embeddings": True},
    )


def get_embeddings(model_name: str = DEFAULT_EMBEDDING_MODEL) -> HuggingFaceEmbeddings:
    """
    Return a HuggingFaceEmbeddings instance.

    When called from inside a Streamlit run we wrap the construction in
    `st.cache_resource` so the model is loaded exactly once per process.
    Outside Streamlit (CLI / __main__) we fall back to a plain build.
    """
    try:
        import streamlit as st  # noqa: WPS433

        @st.cache_resource(show_spinner="Loading embedding model...")
        def _cached(name: str) -> HuggingFaceEmbeddings:
            return _build_embeddings(name)

        return _cached(model_name)
    except Exception:
        return _build_embeddings(model_name)
