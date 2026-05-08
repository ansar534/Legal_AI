"""Hybrid (BM25 + dense) retriever construction."""

from __future__ import annotations

from typing import List, Optional, Sequence

from langchain_chroma import Chroma
from langchain_classic.retrievers import EnsembleRetriever
from langchain_community.retrievers import BM25Retriever
from langchain_core.documents import Document


def build_hybrid_retriever(
    vectordb: Chroma,
    chunks: List[Document],
    vector_k: int = 8,
    fetch_k: int = 30,
    lambda_mult: float = 0.5,
    bm25_k: int = 8,
    weights: Sequence[float] = (0.4, 0.6),
    filter_filenames: Optional[List[str]] = None,
) -> EnsembleRetriever:
    """
    Combine BM25 (sparse) with MMR vector search (dense).

    ``filter_filenames`` is critical for the "use existing documents"
    subset case. The persistent Chroma collection is shared across runs
    and may contain chunks from MANY files; when the user has selected a
    subset we must constrain the dense retriever to those files only,
    otherwise the LLM gets hits from documents the user didn't pick.
    BM25 is naturally constrained because it indexes the ``chunks``
    argument directly.
    """
    search_kwargs: dict = {
        "k": vector_k,
        "fetch_k": fetch_k,
        "lambda_mult": lambda_mult,
    }
    if filter_filenames:
        # Chroma `where` filter syntax. ``$in`` matches any of the given
        # values. Single-value lists work as well; we always use $in for
        # uniformity.
        search_kwargs["filter"] = {
            "filename": {"$in": list(filter_filenames)}
        }

    vector_retriever = vectordb.as_retriever(
        search_type="mmr",
        search_kwargs=search_kwargs,
    )

    bm25_retriever = BM25Retriever.from_documents(chunks)
    bm25_retriever.k = bm25_k

    return EnsembleRetriever(
        retrievers=[bm25_retriever, vector_retriever],
        weights=list(weights),
    )


def format_docs_with_citations(docs: List[Document]) -> str:
    """
    Prompt-friendly rendering of retrieved documents.

    Page metadata is only emitted when the source actually has pages
    (PDFs from PyPDFLoader). Plain text and CSV documents have no
    notion of a page, so we omit the line entirely instead of writing
    ``PAGE: ?`` (which previously caused the LLM to literally cite
    "page ?").
    """
    blocks = []
    for d in docs:
        filename = d.metadata.get("filename", "unknown")
        page = d.metadata.get("page")
        header = f"FILE: {filename}"
        if isinstance(page, int):
            # PyPDFLoader uses 0-based page indices; show 1-based to humans.
            header += f"\nPAGE: {page + 1}"
        blocks.append(f"{header}\n\n{d.page_content}")
    return "\n\n------------------\n\n".join(blocks)


# Shared output-format rules included in every Q&A prompt so the LLM
# stops emitting raw HTML (<br>, <table>, etc.) inside markdown cells
# and standardises on plain markdown that Streamlit's st.markdown can
# render correctly without ``unsafe_allow_html=True``.
FORMATTING_RULES = """\
Output formatting rules (STRICT):
- Use Markdown only. NEVER use HTML tags. No <br>, <b>, <p>, <table>, etc.
- Do NOT render answers as Markdown tables; use bullet points and
  short paragraphs instead.
- Use bullet lists with '-' or numbered lists with '1.', '2.'.
- Use real newlines for line breaks, never <br>.
- Citation format:
    * If the source has a page number (you will see a line "PAGE: N" in
      the retrieved context), cite as [filename.ext, page N].
    * If the source has NO page line, cite as [filename.ext] only.
      Never write "page ?" or invent page numbers.
- Use only plain ASCII square brackets. Do NOT use full-width or
  non-ASCII bracket characters of any kind.
- Bold with **double asterisks**, italics with *single asterisks*.
"""
