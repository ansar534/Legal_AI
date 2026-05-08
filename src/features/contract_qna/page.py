"""Streamlit page for Contract Q&A."""

from __future__ import annotations

from typing import Any, Dict, List

import streamlit as st

from src.core import chunking, loaders, retrievers, ui, vectordb
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
)


_RETRIEVER_KEY = "contract_qna__retriever_bundle"
_CHAT_KEY = "contract_qna__chat"


def _get_or_build_retriever(source: DataSource) -> Dict[str, Any]:
    bundle = st.session_state.get(_RETRIEVER_KEY)
    sig = source.signature()

    if bundle and bundle.get("signature") == sig:
        return bundle

    with st.status("Indexing contracts...", expanded=False) as status:
        status.update(label="Loading text files...")
        docs = loaders.load_files_dispatch(source.files)
        st.write(f"Loaded {len(docs)} documents from {len(source.files)} file(s).")

        status.update(label="Splitting into chunks...")
        chunks = chunking.split_documents(
            docs,
            chunk_size=1000,
            chunk_overlap=150,
            separators=["\n\n", "\n", ".", " "],
        )
        st.write(f"Created {len(chunks)} chunks.")

        status.update(label="Building / loading vector store...")
        vdb = vectordb.get_or_create_vectordb(
            chunks=chunks,
            persist_path=source.persist_path,
            collection_name=source.collection_name,
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


def _render_chat(retriever) -> None:
    history: List[Dict[str, str]] = st.session_state.setdefault(_CHAT_KEY, [])

    for msg in history:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    question = st.chat_input("Ask about the contract(s)...")
    if not question:
        return

    history.append({"role": "user", "content": question})
    with st.chat_message("user"):
        st.markdown(question)

    with st.chat_message("assistant"):
        try:
            with st.spinner("Analysing..."):
                response = build_qna_chain(retriever).invoke({"question": question})
            answer = getattr(response, "content", str(response))
        except Exception as exc:  # noqa: BLE001
            answer = f"Error: {exc}"
        st.markdown(answer)
        history.append({"role": "assistant", "content": answer})


def render() -> None:
    st.title(SPEC.title)
    st.caption(SPEC.description)

    source = ui.source_picker(SPEC)
    if source is None:
        st.info(
            "Choose **Use existing documents** or upload a contract `.txt` "
            "from the sidebar to get started."
        )
        return
    if not source.files:
        st.warning("No files selected. Pick at least one from the sidebar.")
        return

    st.markdown(f"**Active source:** {source.label}")
    with st.expander("Files in scope", expanded=False):
        for f in source.files[:50]:
            st.markdown(f"- `{f.name}`")
        if len(source.files) > 50:
            st.caption(f"... and {len(source.files) - 50} more.")

    bundle = _get_or_build_retriever(source)
    _render_chat(bundle["retriever"])
