"""
Streamlit page for the Compliance Audit Generator.

Wires the source picker -> loaders -> vector DB -> retriever, then renders
two tabs: a structured "Generate Audit Report" and a free-form "Ask Questions"
chat. Heavy artifacts are cached in ``st.session_state`` keyed by the active
data source so tab switches and reruns don't rebuild anything.
"""

from __future__ import annotations

from typing import Any, Dict, List

import streamlit as st

from src.core import chunking, loaders, retrievers, ui, vectordb
from src.core.config import DATA_DIR
from src.core.schemas import DataSource
from src.features.audit_compliance.pipeline import (
    AuditReport,
    build_audit_report_chain,
    build_qna_chain,
)

# FeatureSpec is defined in src/features/__init__.py and imported here.
# This is a deliberate two-way import: src/features/__init__.py imports SPEC
# from this module *after* it has defined FeatureSpec, so by the time Python
# resolves this import the FeatureSpec symbol is already available on the
# partially-initialised parent module.
from src.features import FeatureSpec  # noqa: E402


SPEC = FeatureSpec(
    key="audit_compliance",
    title="Compliance Audit Generator",
    icon=":material/policy:",
    page_render=lambda: render(),
    default_collection="auditcompliance",
    data_folder=DATA_DIR / "Compliance",
    supported_uploads=["pdf"],
    description=(
        "Streamline compliance audits by automatically identifying gaps, "
        "discrepancies, and outdated procedures across your documents."
    ),
)


# ---------------------------------------------------------------------------
# Session state helpers
# ---------------------------------------------------------------------------

_RETRIEVER_KEY = "audit_compliance__retriever_bundle"
_CHAT_KEY = "audit_compliance__chat"
_REPORT_KEY = "audit_compliance__last_report"


def _get_or_build_retriever(source: DataSource) -> Dict[str, Any]:
    """Build (and cache in session_state) the chunks + vector DB + retriever."""
    bundle = st.session_state.get(_RETRIEVER_KEY)
    sig = source.signature()

    if bundle and bundle.get("signature") == sig:
        return bundle

    with st.status("Indexing documents...", expanded=False) as status:
        status.update(label="Loading files...")
        docs = loaders.load_files_dispatch(source.files)
        st.write(f"Loaded {len(docs)} pages / docs from {len(source.files)} file(s).")

        status.update(label="Splitting into chunks...")
        chunks = chunking.split_documents(docs)
        st.write(f"Created {len(chunks)} chunks.")

        status.update(label="Building / loading vector store...")
        vdb = vectordb.get_or_create_vectordb(
            chunks=chunks,
            persist_path=source.persist_path,
            collection_name=source.collection_name,
        )
        st.write(f"Vector store ready: collection `{source.collection_name}`.")

        status.update(label="Building hybrid retriever...")
        retriever = retrievers.build_hybrid_retriever(
            vdb,
            chunks,
            filter_filenames=[f.name for f in source.files],
        )

        status.update(label="Ready.", state="complete")

    bundle = {
        "signature": sig,
        "source": source,
        "chunks": chunks,
        "vectordb": vdb,
        "retriever": retriever,
    }
    st.session_state[_RETRIEVER_KEY] = bundle
    # Drop stale per-source state when the source changes.
    st.session_state.pop(_REPORT_KEY, None)
    st.session_state[_CHAT_KEY] = []
    return bundle


# ---------------------------------------------------------------------------
# Renderers for the two tabs
# ---------------------------------------------------------------------------

_SEVERITY_COLOR = {
    "high": "red",
    "medium": "orange",
    "low": "green",
}

_RATING_COLOR = {
    "strong": "green",
    "adequate": "blue",
    "needs improvement": "orange",
    "critical": "red",
}


def _severity_badge(severity: str) -> str:
    color = _SEVERITY_COLOR.get(severity.strip().lower(), "gray")
    return f":{color}-badge[{severity}]"


def _rating_badge(rating: str) -> str:
    color = _RATING_COLOR.get(rating.strip().lower(), "gray")
    return f":{color}-badge[{rating}]"


def _render_report(report: AuditReport) -> None:
    st.markdown("### Document summary")
    st.write(report.document_summary)

    st.markdown("### Overall compliance rating")
    st.markdown(_rating_badge(report.overall_compliance_rating))

    st.markdown("---")
    st.markdown(f"### Compliance gaps ({len(report.gaps)})")
    if not report.gaps:
        st.success("No gaps identified.")
    for i, gap in enumerate(report.gaps, 1):
        with st.expander(
            f"{i}. {gap.issue}  -  {gap.severity}",
            expanded=(i == 1),
        ):
            st.markdown(_severity_badge(gap.severity))
            st.markdown(f"**Issue:** {gap.issue}")
            st.markdown(f"**Evidence:** {gap.evidence}")
            page_str = "" if gap.page is None else f", page {gap.page}"
            st.caption(f"Source: {gap.filename}{page_str}")

    st.markdown("---")
    st.markdown(f"### Discrepancies ({len(report.discrepancies)})")
    if not report.discrepancies:
        st.success("No discrepancies identified.")
    for i, d in enumerate(report.discrepancies, 1):
        with st.expander(f"{i}. {d.description}", expanded=False):
            st.markdown(f"**Description:** {d.description}")
            if d.conflicting_points:
                st.markdown("**Conflicting points:**")
                for p in d.conflicting_points:
                    st.markdown(f"- {p}")
            st.markdown(f"**Evidence:** {d.evidence}")

    st.markdown("---")
    st.markdown(f"### Outdated procedures ({len(report.outdated_procedures)})")
    if not report.outdated_procedures:
        st.success("No outdated procedures identified.")
    for i, op in enumerate(report.outdated_procedures, 1):
        with st.expander(f"{i}. {op.procedure}", expanded=False):
            st.markdown(f"**Procedure:** {op.procedure}")
            st.markdown(f"**Why outdated:** {op.why_outdated}")
            st.markdown(f"**Evidence:** {op.evidence}")

    st.markdown("---")
    st.markdown(f"### Recommendations ({len(report.recommendations)})")
    if not report.recommendations:
        st.info("No recommendations returned.")
    for i, rec in enumerate(report.recommendations, 1):
        st.markdown(f"{i}. {rec}")

    st.markdown("---")
    st.download_button(
        label="Download report (JSON)",
        data=report.model_dump_json(indent=2),
        file_name="compliance_audit_report.json",
        mime="application/json",
    )


def _render_report_tab(retriever) -> None:
    st.subheader("Generate audit report")
    st.caption(
        "Click below to run a full compliance audit. The model will surface "
        "gaps, discrepancies and outdated procedures from the selected documents."
    )

    col_run, col_clear = st.columns([1, 1])
    run_clicked = col_run.button("Run audit", type="primary")
    if col_clear.button("Clear last report"):
        st.session_state.pop(_REPORT_KEY, None)

    if run_clicked:
        try:
            with st.spinner("Auditing documents... this may take ~30-60 seconds."):
                report: AuditReport = build_audit_report_chain(retriever).invoke({})
            st.session_state[_REPORT_KEY] = report
            st.success("Audit complete.")
        except Exception as exc:  # noqa: BLE001
            st.error(f"Audit failed: {exc}")
            return

    report = st.session_state.get(_REPORT_KEY)
    if report is not None:
        st.markdown("---")
        _render_report(report)


def _render_chat_tab(retriever) -> None:
    st.subheader("Ask questions")
    st.caption("Free-form Q&A over the same documents. Citations included.")

    history: List[Dict[str, str]] = st.session_state.setdefault(_CHAT_KEY, [])

    for msg in history:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    question = st.chat_input("Ask a compliance question...")
    if not question:
        return

    history.append({"role": "user", "content": question})
    with st.chat_message("user"):
        st.markdown(question)

    with st.chat_message("assistant"):
        try:
            with st.spinner("Thinking..."):
                response = build_qna_chain(retriever).invoke({"question": question})
            answer = getattr(response, "content", str(response))
        except Exception as exc:  # noqa: BLE001
            answer = f"Error: {exc}"

        st.markdown(answer)
        history.append({"role": "assistant", "content": answer})


# ---------------------------------------------------------------------------
# Page entry point (called from streamlit_app.py via FEATURES registry)
# ---------------------------------------------------------------------------

def render() -> None:
    st.title(SPEC.title)
    st.caption(SPEC.description)

    source = ui.source_picker(SPEC)
    if source is None:
        st.info(
            "Choose **Use existing documents** or upload a new file from the "
            "sidebar to get started."
        )
        return

    if not source.files:
        st.warning("No files selected. Pick at least one from the sidebar.")
        return

    st.markdown(f"**Active source:** {source.label}")
    with st.expander("Files in scope", expanded=False):
        for f in source.files:
            st.markdown(f"- `{f.name}`")

    bundle = _get_or_build_retriever(source)
    retriever = bundle["retriever"]

    tab_report, tab_qna = st.tabs(["Generate audit report", "Ask questions"])
    with tab_report:
        _render_report_tab(retriever)
    with tab_qna:
        _render_chat_tab(retriever)
