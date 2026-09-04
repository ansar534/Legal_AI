"""Cached Groq LLM factory.

We use ``functools.lru_cache`` at module level (rather than
``@st.cache_resource`` defined inside ``get_llm``). Decorating an inner
function with ``@st.cache_resource`` is a known Streamlit antipattern -
the cache can return a stale instance built for a *different* set of
args, which previously caused the Q&A chain to inherit ``json_mode=True``
from a prior audit-report call.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Optional

from langchain_groq import ChatGroq

from src.core.config import get_required_env


# Default model used by free-text chains (Q&A, audit-report Q&A, etc.).
DEFAULT_GROQ_MODEL = "openai/gpt-oss-120b"

# Stronger model used by structured (Pydantic) chains. The 20B gpt-oss
# model is known to silently produce empty completions on complex nested
# JSON output - llama-3.3-70b is markedly more reliable at structured
# output and is fast on Groq.
STRUCTURED_OUTPUT_MODEL = "llama-3.3-70b-versatile"


@lru_cache(maxsize=16)
def _cached_llm(
    model: str,
    temperature: float,
    max_tokens: Optional[int],
    json_mode: bool,
) -> ChatGroq:
    """
    Module-level cache. Distinct ``(model, temperature, max_tokens,
    json_mode)`` tuples produce distinct ChatGroq instances; calls with
    identical args are deduped.
    """
    api_key = get_required_env("GROQ_API_KEY")
    kwargs: dict = {
        "model": model,
        "temperature": temperature,
        "groq_api_key": api_key,
    }
    if max_tokens is not None:
        kwargs["max_tokens"] = max_tokens
    if json_mode:
        # Groq supports OpenAI-style JSON mode on most chat models.
        # ChatGroq forwards model_kwargs to the underlying client. We
        # build a *fresh* dict per call to avoid any chance of shared
        # mutable state between instances.
        kwargs["model_kwargs"] = {"response_format": {"type": "json_object"}}
    return ChatGroq(**kwargs)


def get_llm(
    model: str = DEFAULT_GROQ_MODEL,
    temperature: float = 0.2,
    max_tokens: Optional[int] = None,
    json_mode: bool = False,
) -> ChatGroq:
    """Return a ChatGroq instance, deduped by ``(model, temperature,
    max_tokens, json_mode)``.

    JSON-mode contract reminder: when ``json_mode=True``, the prompt
    you compose MUST contain the literal substring ``json`` somewhere
    (Groq enforces this and rejects requests that don't).
    """
    return _cached_llm(model, temperature, max_tokens, json_mode)
