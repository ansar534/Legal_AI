"""
Streamlit page for Contract Risk Analyzer.

Differs from the other features:
- The risky-clauses KB is ALWAYS loaded (no "use existing vs upload" choice).
- The upload sidebar widget is OPTIONAL - users can ask questions against
  the KB alone, OR upload a contract to cross-reference against it.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any, Dict, List, Optional

import pandas as pd
import streamlit as st

from src.core import chunking, loaders, retrievers, vectordb
from src.core.config import CHROMA_ROOT, DATA_DIR, UPLOAD_CHROMA_ROOT
from src.core.loaders import sanitize_for_collection, save_uploaded_file
from src.features import FeatureSpec
from src.features.contract_risk.pipeline import build_chain


KB_FOLDER = DATA_DIR / "Contract_Risk"
KB_COLLECTION = "contract_risk"
KB_CSV_PATH = KB_FOLDER / "legal_contract_clauses.csv"


SPEC = FeatureSpec(
    key="contract_risk",
    title="Contract Risk Analyzer",
    icon=":material/warning:",
    page_render=lambda: render(),
    default_collection=KB_COLLECTION,
    data_folder=KB_FOLDER,
    supported_uploads=["pdf", "txt"],
    description=(
        "Identify risky clauses against a curated risk knowledge base. "
        "Optionally upload your own contract to cross-reference."
    ),
)


_KB_KEY = "contract_risk__kb_bundle"
_CONTRACT_KEY = "contract_risk__contract_bundle"
_CHAT_KEY = "contract_risk__chat"


# ---------------------------------------------------------------------------
# KB loader (always cached for the session)
# ---------------------------------------------------------------------------

def _load_kb_documents() -> List:
    """Load every file in the KB folder as Documents (PDF + CSV supported)."""
    if not KB_FOLDER.exists():
        raise FileNotFoundError(
            f"Knowledge base folder missing: {KB_FOLDER}"
        )
    files = sorted(
        list(KB_FOLDER.glob("*.pdf"))
        + list(KB_FOLDER.glob("*.csv"))
        + list(KB_FOLDER.glob("*.txt"))
    )
    if not files:
        raise ValueError(f"No KB files found in {KB_FOLDER}")

    docs = loaders.load_files_dispatch(files)
    # Tag each doc with the source type so the LLM can tell pdf clauses
    # from csv risk-matrix rows.
    for d in docs:
        suffix = (
            d.metadata.get("source_path", "").lower().rsplit(".", 1)[-1]
            if d.metadata.get("source_path")
            else ""
        )
        d.metadata.setdefault("source_type", suffix or "unknown")
        d.metadata.setdefault("category", "risk_kb")
    return docs


def _get_or_build_kb() -> Dict[str, Any]:
    bundle = st.session_state.get(_KB_KEY)
    if bundle:
        return bundle

    with st.status("Loading risk knowledge base...", expanded=True) as status:
        try:
            status.update(label="Loading PDF + CSV...")
            docs = _load_kb_documents()
            st.write(f"Loaded {len(docs)} KB documents.")

            status.update(label="Chunking...")
            chunks = chunking.split_documents(
                docs, chunk_size=1000, chunk_overlap=200,
                separators=["\n\n", "\n", ".", ";"],
            )
            st.write(f"Created {len(chunks)} KB chunks.")

            status.update(label="Building / loading vector store...")
            vdb = vectordb.get_or_create_vectordb(
                chunks=chunks,
                persist_path=CHROMA_ROOT,
                collection_name=KB_COLLECTION,
            )

            status.update(label="Building hybrid retriever...")
            # Smaller k than other features: contract_risk often combines
            # KB context with USER CONTRACT context, so we keep both context
            # blocks compact to stay well under the LLM token budget.
            retriever = retrievers.build_hybrid_retriever(
                vdb, chunks, vector_k=4, bm25_k=4
            )
            status.update(label="KB ready.", state="complete")
        except Exception as exc:  # noqa: BLE001
            status.update(label=f"KB load failed: {exc}", state="error")
            raise

    bundle = {"retriever": retriever, "chunks": chunks}
    st.session_state[_KB_KEY] = bundle
    return bundle


# ---------------------------------------------------------------------------
# Optional uploaded contract
# ---------------------------------------------------------------------------

def _get_or_build_contract(uploaded_file) -> Dict[str, Any]:
    """Build (and cache) a retriever over a single uploaded contract."""
    bundle = st.session_state.get(_CONTRACT_KEY)
    if bundle and bundle.get("filename") == uploaded_file.name:
        return bundle

    upload_dir = KB_FOLDER / "uploaded_contracts"
    saved_path = save_uploaded_file(uploaded_file, upload_dir)
    sanitized = sanitize_for_collection(saved_path.name)
    persist_path = UPLOAD_CHROMA_ROOT / sanitized
    collection_name = f"upload_{sanitized}"

    with st.status(f"Indexing {saved_path.name}...", expanded=True) as status:
        try:
            status.update(label="Loading file...")
            docs = loaders.load_files_dispatch([saved_path])
            for d in docs:
                d.metadata.setdefault("category", "user_contract")

            status.update(label="Chunking...")
            chunks = chunking.split_documents(docs)

            status.update(label="Building / loading vector store...")
            vdb = vectordb.get_or_create_vectordb(
                chunks=chunks,
                persist_path=persist_path,
                collection_name=collection_name,
            )

            status.update(label="Building hybrid retriever...")
            retriever = retrievers.build_hybrid_retriever(
                vdb, chunks, vector_k=4, bm25_k=4
            )
            status.update(label="Contract indexed.", state="complete")
        except Exception as exc:  # noqa: BLE001
            status.update(label=f"Indexing failed: {exc}", state="error")
            raise

    bundle = {
        "filename": uploaded_file.name,
        "saved_path": saved_path,
        "retriever": retriever,
        "chunks": chunks,
    }
    st.session_state[_CONTRACT_KEY] = bundle
    return bundle


# ---------------------------------------------------------------------------
# Browse risky clauses (CSV explorer)
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def _load_clauses_dataframe() -> pd.DataFrame:
    """Load the curated clause risk matrix from disk."""
    if not KB_CSV_PATH.exists():
        raise FileNotFoundError(f"Clause CSV missing: {KB_CSV_PATH}")
    df = pd.read_csv(KB_CSV_PATH)
    expected = {"clause_text", "clause_type", "risk_level"}
    missing = expected - set(df.columns)
    if missing:
        raise ValueError(f"Clause CSV missing columns: {sorted(missing)}")
    df = df.dropna(subset=["clause_text"]).copy()
    df["risk_level"] = df["risk_level"].astype(str).str.strip().str.lower()
    df["clause_type"] = df["clause_type"].astype(str).str.strip()
    return df


def _render_clause_browser() -> None:
    """Filterable table over the risky-clause knowledge base CSV."""
    with st.expander("Browse risky clauses", expanded=False):
        try:
            df = _load_clauses_dataframe()
        except Exception as exc:  # noqa: BLE001
            st.warning(f"Could not load clause browser: {exc}")
            return

        st.caption(
            f"{len(df):,} clauses in `{KB_CSV_PATH.name}`. "
            "Filter below to inspect the knowledge base without asking the LLM."
        )

        levels = sorted(df["risk_level"].dropna().unique().tolist())
        types = sorted(df["clause_type"].dropna().unique().tolist())

        col_level, col_type, col_search = st.columns([1, 2, 2])
        with col_level:
            selected_levels = st.multiselect(
                "Risk level",
                options=levels,
                default=["high"] if "high" in levels else levels[:1],
                key="contract_risk__browse_levels",
            )
        with col_type:
            selected_types = st.multiselect(
                "Clause type",
                options=types,
                default=[],
                key="contract_risk__browse_types",
                help="Leave empty to include all clause types.",
            )
        with col_search:
            text_query = st.text_input(
                "Search clause text",
                value="",
                key="contract_risk__browse_search",
                placeholder="e.g. uncapped liability",
            )

        filtered = df
        if selected_levels:
            filtered = filtered[filtered["risk_level"].isin(selected_levels)]
        if selected_types:
            filtered = filtered[filtered["clause_type"].isin(selected_types)]
        if text_query.strip():
            needle = text_query.strip().lower()
            filtered = filtered[
                filtered["clause_text"].astype(str).str.lower().str.contains(
                    needle, na=False, regex=False
                )
            ]

        st.caption(f"Showing {len(filtered):,} of {len(df):,} clauses.")
        st.dataframe(
            filtered[["risk_level", "clause_type", "clause_text"]],
            use_container_width=True,
            hide_index=True,
            height=320,
        )


# ---------------------------------------------------------------------------
# Chat
# ---------------------------------------------------------------------------

def _render_chat(kb_retriever, contract_retriever) -> None:
    history: List[Dict[str, str]] = st.session_state.setdefault(_CHAT_KEY, [])

    for msg in history:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    question = st.chat_input("Ask about contract risks...")
    if not question:
        return

    history.append({"role": "user", "content": question})
    with st.chat_message("user"):
        st.markdown(question)

    with st.chat_message("assistant"):
        try:
            with st.spinner("Analysing risks..."):
                response = build_chain(kb_retriever, contract_retriever).invoke(
                    {"question": question}
                )
            answer = getattr(response, "content", str(response))
        except Exception as exc:  # noqa: BLE001
            answer = f"Error: {exc}"
        st.markdown(answer)
        history.append({"role": "assistant", "content": answer})


# ---------------------------------------------------------------------------
# Page entry point
# ---------------------------------------------------------------------------

def render() -> None:
    st.title(SPEC.title)
    st.caption(SPEC.description)

    # Sidebar: optional contract upload (KB is always loaded automatically)
    st.sidebar.markdown(f"### {SPEC.title}")
    st.sidebar.caption(SPEC.description)
    st.sidebar.markdown("**Risk knowledge base:** always loaded automatically.")

    uploaded = st.sidebar.file_uploader(
        "Optionally upload your own contract",
        type=SPEC.supported_uploads,
        accept_multiple_files=False,
        key="contract_risk__upload",
        help="When uploaded, your contract is cross-referenced against the KB.",
    )

    if st.sidebar.button("Clear uploaded contract"):
        st.session_state.pop(_CONTRACT_KEY, None)
        st.session_state.pop(_CHAT_KEY, None)
        st.rerun()

    # Always load the KB
    try:
        kb_bundle = _get_or_build_kb()
    except Exception as exc:  # noqa: BLE001
        st.error(f"Failed to load risk knowledge base: {exc}")
        return

    # Optional contract retriever
    contract_bundle = None
    if uploaded is not None:
        try:
            contract_bundle = _get_or_build_contract(uploaded)
        except Exception as exc:  # noqa: BLE001
            st.error(f"Failed to index uploaded contract: {exc}")
            contract_bundle = None
    else:
        # Drop stale per-contract state when the user removes the upload.
        st.session_state.pop(_CONTRACT_KEY, None)

    if contract_bundle:
        st.success(
            f"Active sources: **risk KB** ({len(kb_bundle['chunks'])} chunks) "
            f"+ **your contract** `{contract_bundle['filename']}` "
            f"({len(contract_bundle['chunks'])} chunks)."
        )
        st.caption(
            "Questions are answered using BOTH sources. The LLM will "
            "cross-reference your clauses against the KB."
        )
    else:
        st.info(
            f"Active source: **risk KB only** "
            f"({len(kb_bundle['chunks'])} chunks). "
            f"Upload a contract from the sidebar to add it as a second source."
        )

    _render_clause_browser()

    contract_retriever = contract_bundle["retriever"] if contract_bundle else None
    _render_chat(kb_bundle["retriever"], contract_retriever)
