"""Streamlit page for Contract Q&A."""

from __future__ import annotations

from typing import Any, Dict

import streamlit as st

from src.core import chunking, retrievers, ui, vectordb
from src.core.config import DATA_DIR
from src.core.schemas import DataSource
from src.features import FeatureSpec
from src.features.contract_qna.pipeline import build_qna_chain


SPEC = FeatureSpec(
    key="contract_qna",
    title="Contract Q&A",
    icon=":material/description:",
    page_render=lambda: render(),
    default_collection="contracts_db",
    data_folder=DATA_DIR / "Contract_Renewal_QNA",
    supported_uploads=["txt"],
    description=(
        "Question & answer over contract text files. Answers are organised "
        "into Rights, Obligations, Risks, and Exceptions."
    ),
    suggestions=[
        "What are the termination rights of each party?",
        "Summarise the renewal terms and notice periods.",
        "What are the payment obligations and deadlines?",
        "Are there any exclusivity or non-compete clauses?",
    ],
)


_RETRIEVER_KEY = "contract_qna__retriever_bundle"
_CHAT_KEY = "contract_qna__chat"


def _get_or_build_retriever(source: DataSource) -> Dict[str, Any]:
    bundle = st.session_state.get(_RETRIEVER_KEY)
    sig = source.signature()

    if bundle and bundle.get("signature") == sig:
        return bundle

    with st.status("Loading contracts from the database...", expanded=False) as status:
        vdb, chunks = vectordb.index_files(
            source.collection_name,
            source.files,
            lambda docs: chunking.split_documents(
                docs,
                chunk_size=1000,
                chunk_overlap=150,
                separators=["\n\n", "\n", ".", " "],
            ),
            on_progress=st.write,
        )

        status.update(label="Building hybrid retriever...")
        retriever = retrievers.build_hybrid_retriever(
            vdb,
            chunks,
            vector_k=6,
            bm25_k=6,
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
        st.info("Upload a contract `.txt` from the sidebar to get started.")
        return

    retriever = _get_or_build_retriever(source)["retriever"]
    ui.chat(
        SPEC,
        _CHAT_KEY,
        lambda: build_qna_chain(retriever),
        placeholder="Ask about the contract(s)...",
    )
