"""Streamlit page for Policies Q&A."""

from __future__ import annotations

from typing import Any, Dict

import streamlit as st

from src.core import chunking, retrievers, ui, vectordb
from src.core.config import DATA_DIR
from src.core.schemas import DataSource
from src.features import FeatureSpec
from src.features.policies_qna.pipeline import build_qna_chain


SPEC = FeatureSpec(
    key="policies_qna",
    title="Policies Q&A",
    icon=":material/gavel:",
    page_render=lambda: render(),
    default_collection="Policies_QNA",
    data_folder=DATA_DIR / "Policies_QNA",
    supported_uploads=["pdf"],
    description=(
        "Ask precise questions over company / regulatory policies, "
        "with citations to the source documents."
    ),
    suggestions=[
        "What does the anti-corruption policy say about gifts and hospitality?",
        "How do I report a concern under the whistleblowing policy?",
        "What are the global trade compliance obligations?",
        "Summarise the human rights policy commitments.",
    ],
)


_RETRIEVER_KEY = "policies_qna__retriever_bundle"
_CHAT_KEY = "policies_qna__chat"


def _get_or_build_retriever(source: DataSource) -> Dict[str, Any]:
    bundle = st.session_state.get(_RETRIEVER_KEY)
    sig = source.signature()

    if bundle and bundle.get("signature") == sig:
        return bundle

    with st.status("Loading policy documents from the database...", expanded=False) as status:
        vdb, chunks = vectordb.index_files(
            source.collection_name,
            source.files,
            chunking.split_documents,
            on_progress=st.write,
        )

        status.update(label="Building hybrid retriever...")
        retriever = retrievers.build_hybrid_retriever(
            vdb,
            chunks,
            filter_filenames=[f.name for f in source.files],
        )
        status.update(label="Ready.", state="complete")

    bundle = {
        "signature": sig,
        "retriever": retriever,
        "chunks": chunks,
    }
    st.session_state[_RETRIEVER_KEY] = bundle
    st.session_state[_CHAT_KEY] = []
    return bundle


def render() -> None:
    ui.page_header(SPEC)
    ui.new_chat_button(_CHAT_KEY)

    source = ui.source_picker(SPEC)
    if source is None:
        st.info("Upload a policy PDF from the sidebar to get started.")
        return

    retriever = _get_or_build_retriever(source)["retriever"]
    ui.chat(
        SPEC,
        _CHAT_KEY,
        lambda: build_qna_chain(retriever),
        placeholder="Ask a policy question...",
    )
