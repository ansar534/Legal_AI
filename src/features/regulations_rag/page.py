"""Streamlit page for live Regulations Search."""

from __future__ import annotations

from typing import Any, Dict, List

import streamlit as st

from src.core.config import PROJECT_ROOT
from src.features import FeatureSpec
from src.features.regulations_rag.pipeline import (
    DEFAULT_MAX_APIFY_ITEMS,
    DEFAULT_TOP_K,
    RegulationsAnswer,
    run_regulations_search,
)


# This feature does not use local files - it fetches live from Apify.
SPEC = FeatureSpec(
    key="regulations_rag",
    title="Regulations Search (live)",
    icon=":material/public:",
    page_render=lambda: render(),
    default_collection="regulations_rag",
    data_folder=None,
    supported_uploads=[],
    description=(
        "Live search of U.S. federal regulations via Apify + "
        "Regulations.gov. Type a question and the system fetches, embeds, "
        "and answers in one go."
    ),
)


_RESULT_KEY = "regulations_rag__last_result"
_LOG_KEY = "regulations_rag__last_log"


def _render_result(result: RegulationsAnswer) -> None:
    st.markdown("### Answer")
    st.write(result.answer)

    st.markdown(f"### Sources ({len(result.sources)})")
    if not result.sources:
        st.caption("No sources cited.")
        return

    for i, src in enumerate(result.sources, 1):
        with st.expander(f"[{i}] {src.title}", expanded=(i == 1)):
            st.markdown(f"- **Agency:** {src.agency}")
            st.markdown(f"- **Posted:** {src.posted_date}")
            st.markdown(f"- **Content kind:** {src.content_kind}")
            if src.url:
                st.markdown(f"- **URL:** {src.url}")


def render() -> None:
    st.title(SPEC.title)
    st.caption(SPEC.description)

    st.sidebar.markdown(f"### {SPEC.title}")
    st.sidebar.caption(
        "Configure the live search parameters. Each run hits Apify + "
        "Regulations.gov and may take 30-90 seconds."
    )

    agency_id = st.sidebar.text_input(
        "Agency filter (optional)",
        value="",
        help="Leave blank to search across all agencies (e.g. EPA, FDA).",
        key="regulations_rag__agency",
    )
    max_items = st.sidebar.slider(
        "Max documents to fetch",
        min_value=5,
        max_value=50,
        value=DEFAULT_MAX_APIFY_ITEMS,
        step=5,
        key="regulations_rag__max_items",
    )
    top_k = st.sidebar.slider(
        "Top-K chunks for the LLM",
        min_value=3,
        max_value=15,
        value=DEFAULT_TOP_K,
        key="regulations_rag__top_k",
    )

    if st.sidebar.button("Clear last result"):
        st.session_state.pop(_RESULT_KEY, None)
        st.session_state.pop(_LOG_KEY, None)

    st.markdown(
        "Enter your regulations question below. "
        "The pipeline will fetch documents from Regulations.gov via Apify, "
        "embed them, and answer using Groq."
    )

    with st.form("regulations_search_form", clear_on_submit=False):
        query = st.text_area(
            "Your question",
            value="",
            height=100,
            placeholder=(
                "e.g. What are the latest EPA rules on per- and "
                "polyfluoroalkyl substances (PFAS)?"
            ),
        )
        submit = st.form_submit_button("Run search", type="primary")

    if submit:
        if not query.strip():
            st.warning("Please enter a question.")
        else:
            log_lines: List[str] = []

            def _on_status(msg: str) -> None:
                log_lines.append(msg)

            chroma_dir = str(PROJECT_ROOT / ".chromadb")

            with st.status("Running live regulations search...", expanded=True) as status:
                status_placeholder = st.empty()

                def _wrapped_status(msg: str) -> None:
                    log_lines.append(msg)
                    status_placeholder.markdown(
                        "```\n" + "\n".join(log_lines[-20:]) + "\n```"
                    )

                try:
                    result = run_regulations_search(
                        query=query.strip(),
                        agency_id=agency_id.strip(),
                        max_items=max_items,
                        top_k=top_k,
                        chroma_dir=chroma_dir,
                        on_status=_wrapped_status,
                    )
                    status.update(label="Search complete.", state="complete")
                    st.session_state[_RESULT_KEY] = result
                    st.session_state[_LOG_KEY] = log_lines
                except Exception as exc:  # noqa: BLE001
                    status.update(label="Search failed.", state="error")
                    st.error(f"Pipeline error: {exc}")
                    st.session_state[_LOG_KEY] = log_lines
                    return

    result: RegulationsAnswer | None = st.session_state.get(_RESULT_KEY)
    if result is not None:
        st.markdown("---")
        _render_result(result)

    log = st.session_state.get(_LOG_KEY)
    if log:
        with st.expander("Pipeline log", expanded=False):
            st.code("\n".join(log), language="text")
