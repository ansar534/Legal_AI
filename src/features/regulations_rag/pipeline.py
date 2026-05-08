"""
Live Regulations RAG pipeline (Streamlit-free).

Lifted from the original ``src/regulations_rag.py`` script and split into
small composable functions so the Streamlit page can drive each stage
with progress feedback. Behaviour is unchanged.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

import chromadb
import requests
from apify_client import ApifyClient
from groq import Groq
from sentence_transformers import SentenceTransformer

from src.core.config import get_required_env, load_env


# ---------------------------------------------------------------------------
# Tunables (mirror the original script)
# ---------------------------------------------------------------------------

APIFY_ACTOR_ID = "TWljzbHuXIrynSsKE"
EMBEDDING_MODEL_NAME = "all-MiniLM-L6-v2"
GROQ_MODEL_NAME = "openai/gpt-oss-20b"
DEFAULT_MAX_APIFY_ITEMS = 20
DEFAULT_TOP_K = 5
CHUNK_SIZE = 500  # words per chunk
CHROMA_COLLECTION_NAME = "regulations_rag"


# ---------------------------------------------------------------------------
# Status callback used so the Streamlit page can render live progress
# without this module importing streamlit.
# ---------------------------------------------------------------------------

StatusCallback = Callable[[str], None]


def _noop(_: str) -> None:
    return None


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class RetrievedSource:
    title: str
    agency: str
    posted_date: str
    url: str
    content_kind: str
    text: str


@dataclass
class RegulationsAnswer:
    query: str
    answer: str
    sources: List[RetrievedSource] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Helpers (lifted ~unchanged from the original script)
# ---------------------------------------------------------------------------

def _extract_summary_text(item: Dict[str, Any]) -> str:
    for key in ("summary", "abstract", "description", "excerpt"):
        val = item.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return ""


def _fetch_full_text(document_id: str, api_key: str) -> str:
    if not document_id or not api_key:
        return ""
    url = f"https://api.regulations.gov/v4/documents/{document_id}"
    try:
        resp = requests.get(url, params={"api_key": api_key}, timeout=10)
        if resp.status_code != 200:
            return ""
        attrs = resp.json().get("data", {}).get("attributes", {})
        for key in ("fullText", "frSummary", "topics", "title"):
            val = attrs.get(key)
            if isinstance(val, str) and len(val) > 50:
                return val.strip()
    except Exception:
        return ""
    return ""


def _chunk_text(text: str, chunk_size: int = CHUNK_SIZE) -> List[str]:
    words = text.split()
    return [
        " ".join(words[i : i + chunk_size])
        for i in range(0, len(words), chunk_size)
    ]


def _fetch_regulations(
    apify_client: ApifyClient,
    query: str,
    max_items: int,
    agency_id: str,
    on_status: StatusCallback,
) -> List[Dict[str, Any]]:
    actor_input = {
        "searchTerm": query,
        "dataType": "documents",
        "maxItems": max_items,
        "sortBy": "-lastModifiedDate",
        "agencyId": agency_id or "",
        "proxyConfiguration": {"useApifyProxy": False},
        "sp_intended_usage": "Academic research on U.S. federal regulations",
        "sp_improvement_suggestions": "None",
        "sp_contact": "your-email@gmail.com",
    }

    on_status(f"Starting Apify actor for query: '{query}'...")
    run = apify_client.actor(APIFY_ACTOR_ID).start(run_input=actor_input)
    on_status(f"Apify run started (id: {run['id']}). Polling status...")

    while True:
        run = apify_client.run(run["id"]).get()
        status = run["status"]
        on_status(f"Apify status: {status}")
        if status in ("SUCCEEDED", "FAILED", "ABORTED"):
            break
        time.sleep(5)

    if run["status"] != "SUCCEEDED":
        on_status(f"Apify run did not succeed: {run['status']}")
        return []

    dataset_id = run.get("defaultDatasetId")
    if not dataset_id:
        return []

    items = list(apify_client.dataset(dataset_id).iterate_items())
    on_status(f"Apify returned {len(items)} documents.")
    return items


def _build_documents(
    items: List[Dict[str, Any]],
    reg_api_key: str,
    on_status: StatusCallback,
) -> List[Dict[str, Any]]:
    docs: List[Dict[str, Any]] = []
    for i, item in enumerate(items):
        title = str(item.get("title", "")).strip()
        doc_id = str(item.get("id", f"doc-{i}")).strip()
        summary = _extract_summary_text(item)

        on_status(
            f"Fetching full text [{i + 1}/{len(items)}]: {title[:60]}..."
        )
        full_text = _fetch_full_text(doc_id, reg_api_key)
        best_text = full_text if len(full_text) > len(summary) else summary
        if not best_text:
            best_text = title

        chunks = _chunk_text(best_text)
        source = "full_text" if full_text else "summary"

        for k, chunk in enumerate(chunks):
            docs.append(
                {
                    "id": f"{doc_id}-chunk-{k}",
                    "text": f"Title: {title}\nContent: {chunk}",
                    "metadata": {
                        "title": title or "Untitled",
                        "agencyId": str(item.get("agencyId", "")),
                        "postedDate": str(item.get("postedDate", "")),
                        "url": str(item.get("url", "")),
                        "source": source,
                        "chunk": k,
                    },
                }
            )
    on_status(f"Built {len(docs)} chunks from {len(items)} documents.")
    return docs


def _reset_collection(chroma: chromadb.ClientAPI, name: str):
    try:
        chroma.delete_collection(name=name)
    except Exception:
        pass
    return chroma.create_collection(name=name)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def run_regulations_search(
    query: str,
    *,
    agency_id: str = "",
    max_items: int = DEFAULT_MAX_APIFY_ITEMS,
    top_k: int = DEFAULT_TOP_K,
    chroma_dir: str = ".chromadb",
    on_status: Optional[StatusCallback] = None,
) -> RegulationsAnswer:
    """
    End-to-end live regulations search.

    Wraps the original ``regulations_rag.main()`` pipeline so it can be
    driven from a Streamlit page. Each stage emits a status string via the
    optional ``on_status`` callback (use it to update an ``st.status``).
    """
    status = on_status or _noop

    load_env()
    apify_token = get_required_env("APIFY_TOKEN")
    groq_key = get_required_env("GROQ_API_KEY")
    import os

    reg_api_key = os.getenv("REGULATIONS_API_KEY", "DEMO_KEY")

    apify_client = ApifyClient(apify_token)
    groq_client = Groq(api_key=groq_key)

    # Stage 1: fetch
    items = _fetch_regulations(
        apify_client, query, max_items, agency_id, status
    )
    if not items:
        return RegulationsAnswer(
            query=query,
            answer="No documents returned from Apify. Try a different query.",
            sources=[],
        )

    # Stage 2: build chunks (with optional full-text fetch)
    docs = _build_documents(items, reg_api_key, status)
    if not docs:
        return RegulationsAnswer(
            query=query,
            answer="No usable document content found.",
            sources=[],
        )

    # Stage 3: embed + store
    status(f"Embedding {len(docs)} chunks...")
    embedder = SentenceTransformer(EMBEDDING_MODEL_NAME)
    doc_texts = [d["text"] for d in docs]
    doc_embeddings = embedder.encode(
        doc_texts, convert_to_numpy=True, show_progress_bar=False
    )

    chroma_client = chromadb.PersistentClient(path=chroma_dir)
    collection = _reset_collection(chroma_client, CHROMA_COLLECTION_NAME)
    collection.add(
        ids=[d["id"] for d in docs],
        documents=doc_texts,
        embeddings=[e.tolist() for e in doc_embeddings],
        metadatas=[d["metadata"] for d in docs],
    )
    status(f"Stored {len(docs)} chunks in ChromaDB.")

    # Stage 4: search
    status(f"Searching for top {top_k} relevant chunks...")
    q_emb = embedder.encode([query], convert_to_numpy=True)[0]
    result = collection.query(
        query_embeddings=[q_emb.tolist()],
        n_results=top_k,
        include=["documents", "metadatas", "distances"],
    )
    retrieved_docs = result.get("documents", [[]])[0]
    retrieved_meta = result.get("metadatas", [[]])[0]
    if not retrieved_docs:
        return RegulationsAnswer(
            query=query,
            answer="No relevant chunks found.",
            sources=[],
        )

    # Stage 5: LLM
    status("Generating answer with Groq...")
    context_blocks = []
    for idx, (text, meta) in enumerate(zip(retrieved_docs, retrieved_meta), 1):
        context_blocks.append(
            f"[Source {idx}]\n"
            f"Title: {meta.get('title', '')}\n"
            f"Agency: {meta.get('agencyId', '')}\n"
            f"Date: {meta.get('postedDate', '')}\n"
            f"URL: {meta.get('url', '')}\n"
            f"Content:\n{text}"
        )
    prompt = (
        "You are a legal/compliance assistant specializing in U.S. federal "
        "regulations. Answer the user's question using ONLY the retrieved "
        "regulatory context below. Be specific - cite titles and agencies. "
        "If the context is truly insufficient, clearly state what is "
        "missing.\n\n"
        f"User question: {query}\n\n"
        f"Retrieved context:\n\n" + "\n\n".join(context_blocks)
    )
    response = groq_client.chat.completions.create(
        model=GROQ_MODEL_NAME,
        temperature=0.1,
        max_tokens=900,
        messages=[{"role": "user", "content": prompt}],
    )
    answer_text = (response.choices[0].message.content or "").strip() or "No answer generated."

    # De-dupe sources by URL, in original order.
    sources: List[RetrievedSource] = []
    seen = set()
    for meta in retrieved_meta:
        url = meta.get("url", "")
        if url in seen:
            continue
        seen.add(url)
        sources.append(
            RetrievedSource(
                title=meta.get("title", "Untitled"),
                agency=meta.get("agencyId", "N/A"),
                posted_date=meta.get("postedDate", "N/A"),
                url=url,
                content_kind=meta.get("source", "summary"),
                text="",
            )
        )

    status("Done.")
    return RegulationsAnswer(query=query, answer=answer_text, sources=sources)
