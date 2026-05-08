"""Litigation Support - Pydantic-structured RAG + CourtListener live search.

CourtListener flow:
  1. Search API  →  list of cases with cluster IDs
  2. Fetch full opinion text per case (parallel HTTP calls)
  3. BM25 within each case text to extract the most query-relevant passages
  4. Format per-case excerpts  →  LLM synthesis  →  CourtListenerAnswer
"""

from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional

import requests
from langchain_community.retrievers import BM25Retriever
from langchain_core.documents import Document
from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import Runnable, RunnableLambda
from langchain_text_splitters import RecursiveCharacterTextSplitter
from pydantic import BaseModel, Field

from src.core.config import get_required_env
from src.core.llm import DEFAULT_GROQ_MODEL, get_llm
from src.core.retrievers import format_docs_with_citations


# =========================================================
# Schemas — Document RAG
# =========================================================

class SourceReference(BaseModel):
    filename: str
    page: Optional[int] = None
    supporting_text: str


class LitigationAnswer(BaseModel):
    question: str
    answer: str
    legal_risk: str = Field(
        ..., description="A clear statement of the legal risk involved."
    )
    recommendation: str = Field(
        ..., description="Recommended next step, based ONLY on the context."
    )
    references: List[SourceReference] = Field(default_factory=list)


# =========================================================
# Schemas — CourtListener live search
# =========================================================

class CourtListenerCase(BaseModel):
    case_name: str
    court: str
    date_filed: Optional[str] = None
    summary: str = Field(..., description="2-4 sentence summary of the case.")
    relevance: str = Field(
        ..., description="Why this case is relevant to the user's query."
    )
    url: str = Field(..., description="Full URL to the case on CourtListener.")


class CourtListenerAnswer(BaseModel):
    question: str
    overview: str = Field(
        ..., description="3-5 sentence overview synthesising findings across all cases."
    )
    cases: List[CourtListenerCase]
    overall_risk: str = Field(
        ..., description="Aggregate legal risk statement based on the cases."
    )
    recommendation: str = Field(
        ..., description="Actionable next step based only on the cases provided."
    )


# =========================================================
# CourtListener API — search
# =========================================================

_CL_BASE_URL   = "https://www.courtlistener.com"
_CL_SEARCH_URL = f"{_CL_BASE_URL}/api/rest/v4/search/"
_CL_OPINION_URL = f"{_CL_BASE_URL}/api/rest/v4/opinions/"

# Max chars of raw opinion text to download per case.
_MAX_OPINION_CHARS = 12000
# Max chars fed to the LLM after BM25 selection (keeps tokens manageable).
_MAX_EXCERPT_CHARS = 2500
# Chunk size when BM25-indexing a single opinion.
_CHUNK_SIZE = 500
_CHUNK_OVERLAP = 50
# How many BM25 passages to lift per case.
_TOP_K_PASSAGES = 3


def _cl_headers(api_key: str) -> Dict[str, str]:
    return {"Authorization": f"Token {api_key}", "Accept": "application/json"}


def _clean_html(text: str) -> str:
    """Strip HTML tags and normalise whitespace."""
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s{2,}", " ", text)
    return text.strip()


def _cluster_id_from_url(absolute_url: str) -> Optional[str]:
    """Extract cluster ID from '/opinion/12345/some-slug/' style paths."""
    m = re.search(r"/opinion/(\d+)/", absolute_url)
    return m.group(1) if m else None


def search_courtlistener(query: str, page_size: int = 5) -> List[Dict[str, Any]]:
    """
    Search CourtListener for opinions matching *query*.

    Returns a list of dicts with keys:
        case_name, court, date_filed, snippet, url, cluster_id
    Raises RuntimeError on API failure or missing key.
    """
    api_key = get_required_env("COURTLISTENER_API_KEY")
    params  = {"q": query, "type": "o", "page_size": page_size}
    resp = requests.get(
        _CL_SEARCH_URL, params=params, headers=_cl_headers(api_key), timeout=20
    )
    if not resp.ok:
        raise RuntimeError(
            f"CourtListener Search API returned {resp.status_code}: {resp.text[:300]}"
        )

    results = []
    for item in resp.json().get("results", []):
        absolute_url = item.get("absolute_url", "")
        cluster_id   = _cluster_id_from_url(absolute_url) or str(item.get("id", ""))
        full_url     = _CL_BASE_URL + absolute_url if absolute_url else _CL_BASE_URL
        results.append(
            {
                "case_name":  item.get("caseName") or item.get("case_name", "Unknown"),
                "court":      item.get("court_id") or item.get("court", ""),
                "date_filed": item.get("dateFiled") or item.get("date_filed", ""),
                "snippet":    _clean_html(item.get("snippet", "")),
                "url":        full_url,
                "cluster_id": cluster_id,
            }
        )
    # CourtListener's search endpoint often ignores page_size and returns its
    # default page (20).  Slice here to respect what the caller requested.
    return results[:page_size]


# =========================================================
# CourtListener API — full opinion text
# =========================================================

def _fetch_opinion_text(cluster_id: str, api_key: str) -> str:
    """
    Fetch the plain text of the first opinion in *cluster_id*.

    Falls back to HTML-stripped ``html_with_citations`` when ``plain_text``
    is absent, then to empty string.  Capped at ``_MAX_OPINION_CHARS``.
    """
    if not cluster_id:
        return ""
    try:
        resp = requests.get(
            _CL_OPINION_URL,
            params={"cluster": cluster_id,
                    "fields": "plain_text,html_with_citations"},
            headers=_cl_headers(api_key),
            timeout=20,
        )
        if not resp.ok:
            return ""
        for opinion in resp.json().get("results", []):
            text = opinion.get("plain_text") or ""
            if not text:
                text = _clean_html(opinion.get("html_with_citations") or "")
            if text:
                return text[:_MAX_OPINION_CHARS]
    except Exception:  # noqa: BLE001 — best-effort, caller has fallback
        pass
    return ""


def fetch_case_texts(cases: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Enrich each case dict with ``full_text`` fetched from CourtListener.

    All HTTP calls run concurrently (up to 5 workers).
    Falls back to the search ``snippet`` when the fetch fails.
    """
    api_key = get_required_env("COURTLISTENER_API_KEY")

    def _enrich(case: Dict[str, Any]) -> Dict[str, Any]:
        text = _fetch_opinion_text(case.get("cluster_id", ""), api_key)
        return {**case, "full_text": text or case.get("snippet", "")}

    enriched: List[Dict[str, Any]] = [None] * len(cases)  # type: ignore[list-item]
    with ThreadPoolExecutor(max_workers=5) as pool:
        futures = {pool.submit(_enrich, c): i for i, c in enumerate(cases)}
        for fut in as_completed(futures):
            enriched[futures[fut]] = fut.result()
    return enriched


# =========================================================
# BM25 passage extraction (per case)
# =========================================================

def _extract_relevant_passages(text: str, query: str) -> str:
    """
    Split *text* into small chunks, BM25-rank them against *query*, and
    return the top-K passages joined by "…".

    When the text is short enough to fit in one chunk, it is returned as-is.
    """
    if not text:
        return "(no text available)"

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=_CHUNK_SIZE, chunk_overlap=_CHUNK_OVERLAP
    )
    chunks = splitter.split_text(text)

    if len(chunks) <= _TOP_K_PASSAGES:
        # Short document — keep everything (still capped)
        return text[:_MAX_EXCERPT_CHARS]

    docs = [Document(page_content=c) for c in chunks]
    try:
        retriever = BM25Retriever.from_documents(docs, k=_TOP_K_PASSAGES)
        top = retriever.invoke(query)
        excerpt = "\n…\n".join(d.page_content for d in top)
    except Exception:  # noqa: BLE001
        excerpt = text[: _CHUNK_SIZE * _TOP_K_PASSAGES]
    return excerpt[:_MAX_EXCERPT_CHARS]


# =========================================================
# Context formatting
# =========================================================

def build_cases_context(
    cases_with_text: List[Dict[str, Any]], query: str
) -> str:
    """
    For each case, run BM25 passage extraction then format as a numbered
    context block for the LLM prompt.
    """
    blocks: List[str] = []
    for i, case in enumerate(cases_with_text, 1):
        excerpt = _extract_relevant_passages(
            case.get("full_text") or case.get("snippet", ""), query
        )
        blocks.append(
            f"[{i}] CASE: {case['case_name']}\n"
            f"    Court:  {case.get('court', 'N/A')}\n"
            f"    Filed:  {case.get('date_filed', 'N/A')}\n"
            f"    URL:    {case['url']}\n"
            f"    RELEVANT PASSAGES FROM OPINION:\n{excerpt}"
        )
    return "\n\n{'='*60}\n\n".join(blocks)


# =========================================================
# CourtListener LLM chain
# =========================================================

def _build_courtlistener_prompt() -> ChatPromptTemplate:
    parser  = PydanticOutputParser(pydantic_object=CourtListenerAnswer)
    safe_fmt = (
        parser.get_format_instructions().replace("{", "{{").replace("}", "}}")
    )
    return ChatPromptTemplate.from_messages(
        [
            (
                "system",
                safe_fmt
                + """

You are a senior Litigation Research Assistant specialising in case law.

You have been given a user's legal query and relevant passages extracted from
actual CourtListener opinions. Your job is to:

1. Write a concise summary for each case (2-4 sentences) based on its passages.
2. Explain why each case is relevant to the user's query.
3. Provide a synthesising overview (3-5 sentences) across all cases.
4. State the aggregate legal risk.
5. Give one actionable recommendation.

Rules:
- Base everything strictly on the provided passages — never invent facts.
- The `url` field for each case MUST be copied verbatim from the input.
- Never invent citations, docket numbers, or dates.
- Return ONLY valid JSON matching the schema above.
""",
            ),
            (
                "human",
                """
QUERY:
{question}

CASES AND EXTRACTED PASSAGES:
{cases_context}

Generate the structured response now.
""",
            ),
        ]
    )


def build_courtlistener_chain() -> Runnable:
    """
    Returns a chain: {"question": str, "cases_context": str} → CourtListenerAnswer.
    """
    llm    = get_llm(model=DEFAULT_GROQ_MODEL, temperature=0.1,
                     max_tokens=4096, json_mode=True)
    parser = PydanticOutputParser(pydantic_object=CourtListenerAnswer)
    return _build_courtlistener_prompt() | llm | parser


# =========================================================
# Document RAG chain (unchanged)
# =========================================================

def _build_prompt() -> ChatPromptTemplate:
    parser = PydanticOutputParser(pydantic_object=LitigationAnswer)
    safe_fmt = (
        parser.get_format_instructions().replace("{", "{{").replace("}", "}}")
    )
    return ChatPromptTemplate.from_messages(
        [
            (
                "system",
                safe_fmt
                + """

You are a senior Litigation Support Assistant.

Use ONLY the provided context.

Rules:
1. Never invent legal references.
2. Always provide source references with filename and (when available) page.
3. Mention legal risk clearly.
4. Give a recommendation based only on the context.
5. If evidence is insufficient, say so explicitly in the answer field.

Return ONLY valid JSON.
""",
            ),
            (
                "human",
                """
QUESTION:
{question}

CONTEXT:
{context}

Generate the structured litigation response now.
""",
            ),
        ]
    )


def build_chain(retriever) -> Runnable:
    """Returns a chain producing a :class:`LitigationAnswer` from local docs."""
    llm    = get_llm(model=DEFAULT_GROQ_MODEL, temperature=0.1,
                     max_tokens=4096, json_mode=True)
    parser = PydanticOutputParser(pydantic_object=LitigationAnswer)
    prompt = _build_prompt()

    def _retrieve_and_format(inputs: Dict[str, Any]) -> str:
        return format_docs_with_citations(retriever.invoke(inputs["question"]))

    return (
        {
            "context":  RunnableLambda(_retrieve_and_format),
            "question": RunnableLambda(lambda x: x["question"]),
        }
        | prompt
        | llm
        | parser
    )


# =========================================================
# Keyword extraction helper
# =========================================================

def extract_search_keywords(text: str) -> str:
    """
    Extract 6-8 legal search keywords from *text* using an LLM call.
    Returns a space-separated string suitable for the CourtListener query box.
    """
    llm = get_llm(model=DEFAULT_GROQ_MODEL, temperature=0.0, max_tokens=128)
    prompt = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                "You are a legal research assistant. "
                "Extract 6-8 concise legal keywords or short phrases from the "
                "provided text that would be useful for searching case law. "
                "Return only the keywords separated by spaces, nothing else.",
            ),
            ("human", "{text}"),
        ]
    )
    result = (prompt | llm).invoke({"text": text[:3000]})
    return getattr(result, "content", str(result)).strip()
