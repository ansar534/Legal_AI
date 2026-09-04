"""Streamlit page for Litigation Support."""

from __future__ import annotations

import hashlib
from typing import Any, Dict, List, Optional

import streamlit as st

from src.core import chunking, loaders, retrievers, ui, vectordb
from src.core.config import DATA_DIR, PROJECT_ROOT
from src.core.schemas import DataSource
from src.features import FeatureSpec
from src.features.litigation.pipeline import (
    CourtListenerAnswer,
    CourtListenerCase,
    LitigationAnswer,
    build_cases_context,
    build_chain,
    build_courtlistener_chain,
    extract_search_keywords,
    fetch_case_texts,
    search_courtlistener,
)


LITIGATION_PERSIST_PATH = PROJECT_ROOT / "vector_store" / "litigation_support"

SPEC = FeatureSpec(
    key="litigation",
    title="Litigation Support",
    icon=":material/balance:",
    page_render=lambda: render(),
    default_collection="litigation_support",
    data_folder=DATA_DIR / "Litigation",
    supported_uploads=["pdf"],
    description=(
        "Find precedents, legal risks, and recommendations for litigation "
        "questions. Returns a structured answer with cited sources."
    ),
    custom_persist_path=LITIGATION_PERSIST_PATH,
)

_RETRIEVER_KEY  = "litigation__retriever_bundle"
_DOC_HISTORY_KEY = "litigation__history"
_CL_CACHE_KEY   = "litigation__cl_cache"   # {query_hash: {"answer": ..., "cases": ...}}
_CL_HISTORY_KEY = "litigation__cl_history"


# ---------------------------------------------------------------------------
# Document Q&A helpers
# ---------------------------------------------------------------------------

def _get_or_build_retriever(source: DataSource) -> Dict[str, Any]:
    bundle = st.session_state.get(_RETRIEVER_KEY)
    sig = source.signature()
    if bundle and bundle.get("signature") == sig:
        return bundle

    with st.status("Indexing litigation documents...", expanded=True) as status:
        try:
            status.update(label="Loading PDFs...")
            docs = loaders.load_files_dispatch(source.files)
            st.write(f"Loaded {len(docs)} pages from {len(source.files)} file(s).")

            status.update(label="Splitting into chunks...")
            chunks = chunking.split_documents(docs, chunk_size=1200, chunk_overlap=200)
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
                vector_k=4,
                fetch_k=14,
                bm25_k=4,
                filter_filenames=[f.name for f in source.files],
            )
            status.update(label="Ready.", state="complete")
        except Exception as exc:
            status.update(label=f"Indexing failed: {exc}", state="error")
            raise

    bundle = {"signature": sig, "retriever": retriever, "chunks": chunks}
    st.session_state[_RETRIEVER_KEY] = bundle
    st.session_state[_DOC_HISTORY_KEY] = []
    return bundle


def _render_lit_answer(ans: LitigationAnswer) -> None:
    st.markdown("### Answer")
    st.write(ans.answer)

    col_risk, col_rec = st.columns(2)
    with col_risk:
        st.markdown("### Legal Risk")
        st.warning(ans.legal_risk)
    with col_rec:
        st.markdown("### Recommendation")
        st.info(ans.recommendation)

    st.markdown(f"### References ({len(ans.references)})")
    if not ans.references:
        st.caption("No references returned.")
    for i, ref in enumerate(ans.references, 1):
        page_str = "" if ref.page is None else f", page {ref.page}"
        with st.expander(f"[{i}] {ref.filename}{page_str}", expanded=(i == 1)):
            st.markdown(ref.supporting_text)

    st.download_button(
        label="Download answer (JSON)",
        data=ans.model_dump_json(indent=2),
        file_name="litigation_answer.json",
        mime="application/json",
        key=f"litigation_dl_{id(ans)}",
    )


def _render_doc_tab(retriever) -> None:
    history: List[Dict[str, Any]] = st.session_state.setdefault(_DOC_HISTORY_KEY, [])

    for entry in history:
        with st.chat_message("user"):
            st.markdown(entry["question"])
        with st.chat_message("assistant"):
            _render_lit_answer(entry["answer"])

    question = st.chat_input("Ask a litigation question about your documents...")
    if not question:
        return

    with st.chat_message("user"):
        st.markdown(question)

    with st.chat_message("assistant"):
        try:
            with st.spinner("Researching your documents..."):
                answer: LitigationAnswer = build_chain(retriever).invoke(
                    {"question": question}
                )
        except Exception as exc:
            st.error(f"Error: {exc}")
            return
        _render_lit_answer(answer)
        history.append({"question": question, "answer": answer})


# ---------------------------------------------------------------------------
# CourtListener helpers
# ---------------------------------------------------------------------------

def _cl_cache_key(query: str, page_size: int) -> str:
    return hashlib.md5(f"{query}|{page_size}".encode()).hexdigest()


def _render_cl_case(
    case: CourtListenerCase,
    index: int,
    raw_case: Optional[Dict[str, Any]] = None,
) -> None:
    """Render one CourtListener case as an expander."""
    with st.expander(f"[{index}] {case.case_name}", expanded=(index == 1)):
        meta_col, link_col = st.columns([3, 1])
        with meta_col:
            st.caption(
                f"**Court:** {case.court or 'N/A'}   |   "
                f"**Filed:** {case.date_filed or 'N/A'}"
            )
        with link_col:
            st.link_button("View on CourtListener ↗", url=case.url)

        st.markdown("**AI Summary**")
        st.write(case.summary)

        st.markdown("**Why this case is relevant**")
        st.info(case.relevance)

        # Show the actual fetched passage so the user can verify the AI's work
        if raw_case:
            excerpt = raw_case.get("full_text") or raw_case.get("snippet", "")
            if excerpt:
                with st.expander("📄 Extracted document passages (raw)", expanded=False):
                    st.text(excerpt[:3000] + ("…" if len(excerpt) > 3000 else ""))


def _render_cl_answer(
    ans: CourtListenerAnswer,
    raw_cases: Optional[List[Dict[str, Any]]] = None,
) -> None:
    st.markdown("### Overview")
    st.write(ans.overview)

    col_risk, col_rec = st.columns(2)
    with col_risk:
        st.markdown("### Overall Legal Risk")
        st.warning(ans.overall_risk)
    with col_rec:
        st.markdown("### Recommendation")
        st.info(ans.recommendation)

    st.markdown(f"### Cases ({len(ans.cases)})")
    raw_by_name: Dict[str, Dict] = {}
    if raw_cases:
        for rc in raw_cases:
            raw_by_name[rc.get("case_name", "")] = rc

    for i, case in enumerate(ans.cases, 1):
        raw = raw_by_name.get(case.case_name)
        _render_cl_case(case, i, raw_case=raw)

    st.download_button(
        label="Download results (JSON)",
        data=ans.model_dump_json(indent=2),
        file_name="courtlistener_results.json",
        mime="application/json",
        key=f"cl_dl_{id(ans)}",
    )


def _render_cl_tab(source: Optional[DataSource]) -> None:
    st.markdown(
        "Search **CourtListener** for relevant case law. "
        "The app fetches the full opinion text, extracts the most relevant "
        "passages using BM25, and then summarises them with an LLM — "
        "every case includes a **live link** back to the source."
    )
    st.divider()

    # ── Query input ──────────────────────────────────────────────────────────
    query = st.text_area(
        "Legal query",
        placeholder="e.g. breach of fiduciary duty investment adviser settlement",
        height=80,
        key="cl_query_input",
    )

    if source and source.files:
        if st.button(
            "Extract keywords from selected document(s)",
            key="cl_extract_btn",
            help="Reads the first selected file and uses AI to extract search terms.",
        ):
            with st.spinner("Extracting keywords…"):
                try:
                    docs = loaders.load_files_dispatch([source.files[0]])
                    raw_text = " ".join(d.page_content for d in docs[:5])
                    keywords = extract_search_keywords(raw_text)
                    st.session_state["cl_query_input"] = keywords
                    st.rerun()
                except Exception as exc:
                    st.error(f"Could not extract keywords: {exc}")

    col_size, col_btn = st.columns([1, 2])
    with col_size:
        page_size = st.slider(
            "Cases to retrieve", min_value=1, max_value=10, value=5
        )
    with col_btn:
        st.write("")
        search_clicked = st.button(
            "Search CourtListener", type="primary", key="cl_search_btn"
        )

    # ── Show history when idle ───────────────────────────────────────────────
    if not search_clicked:
        cl_history: List[Dict[str, Any]] = st.session_state.get(_CL_HISTORY_KEY, [])
        if cl_history:
            st.divider()
            st.markdown("#### Previous searches")
            for entry in reversed(cl_history):
                st.markdown(f"**Query:** {entry['question']}")
                _render_cl_answer(entry["answer"], raw_cases=entry.get("raw_cases"))
                st.divider()
        return

    if not query.strip():
        st.warning("Please enter a query before searching.")
        return

    query    = query.strip()
    cache    = st.session_state.setdefault(_CL_CACHE_KEY, {})
    ck       = _cl_cache_key(query, page_size)

    if ck in cache:
        st.success("Showing cached results.")
        _render_cl_answer(cache[ck]["answer"], raw_cases=cache[ck].get("raw_cases"))
        return

    # ── 4-step pipeline with live status updates ─────────────────────────────
    with st.status("Running CourtListener pipeline…", expanded=True) as status:
        try:
            # Step 1 — search
            status.update(label="Step 1/4 — Searching CourtListener…")
            cases = search_courtlistener(query, page_size=page_size)
            if not cases:
                status.update(label="No cases found.", state="complete")
                st.info(
                    "CourtListener returned no results. "
                    "Try broadening or rephrasing your query."
                )
                return
            st.write(f"✅ Found **{len(cases)}** case(s).")

            # Step 2 — fetch full opinion texts
            status.update(
                label=f"Step 2/4 — Fetching opinion text for {len(cases)} case(s) (parallel)…"
            )
            enriched = fetch_case_texts(cases)
            fetched_count = sum(
                1 for c in enriched
                if c.get("full_text") and c["full_text"] != c.get("snippet", "")
            )
            st.write(
                f"✅ Retrieved full opinion text for **{fetched_count}/{len(enriched)}** "
                f"case(s); using search snippet as fallback for the rest."
            )

            # Step 3 — BM25 passage extraction
            status.update(
                label="Step 3/4 — Extracting relevant passages using BM25…"
            )
            cases_context = build_cases_context(enriched, query)
            total_chars   = sum(
                len(c.get("full_text") or c.get("snippet", "")) for c in enriched
            )
            st.write(
                f"✅ Parsed **{total_chars:,}** chars of opinion text; "
                f"extracted most relevant passages per case."
            )

            # Step 4 — LLM synthesis
            status.update(label="Step 4/4 — Synthesising answer with LLM…")
            answer: CourtListenerAnswer = build_courtlistener_chain().invoke(
                {"question": query, "cases_context": cases_context}
            )
            status.update(label="Done.", state="complete")

        except RuntimeError as exc:
            status.update(label=str(exc), state="error")
            st.error(str(exc))
            return
        except Exception as exc:
            status.update(label=f"Unexpected error: {exc}", state="error")
            st.error(f"Unexpected error: {exc}")
            return

    # ── Cache & render ────────────────────────────────────────────────────────
    cache[ck] = {"answer": answer, "raw_cases": enriched}
    cl_history = st.session_state.setdefault(_CL_HISTORY_KEY, [])
    cl_history.append({"question": query, "answer": answer, "raw_cases": enriched})

    _render_cl_answer(answer, raw_cases=enriched)


# ---------------------------------------------------------------------------
# Main page
# ---------------------------------------------------------------------------

def render() -> None:
    st.title(SPEC.title)
    st.caption(SPEC.description)

    source = ui.source_picker(SPEC)

    tab_docs, tab_cl = st.tabs(["📄 Document Q&A", "⚖️ Search CourtListener"])

    with tab_docs:
        if source is None:
            st.info(
                "Choose **Use existing documents** or upload a litigation PDF "
                "from the sidebar to get started."
            )
        elif not source.files:
            st.warning("No files selected. Pick at least one from the sidebar.")
        else:
            st.markdown(f"**Active source:** {source.label}")
            with st.expander("Files in scope", expanded=False):
                for f in source.files:
                    st.markdown(f"- `{f.name}`")
            bundle = _get_or_build_retriever(source)
            _render_doc_tab(bundle["retriever"])

    with tab_cl:
        _render_cl_tab(source)
