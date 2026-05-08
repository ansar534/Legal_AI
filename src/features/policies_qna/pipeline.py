"""Policies Q&A - pure RAG logic (Streamlit-free)."""

from __future__ import annotations

from typing import Any, Dict

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import Runnable, RunnableLambda

from src.core.llm import get_llm
from src.core.retrievers import FORMATTING_RULES, format_docs_with_citations


QNA_PROMPT = ChatPromptTemplate.from_template(
    """
You are a legal/policy RAG assistant.

Rules:
- Use ONLY the provided context.
- If the answer is not in the context, say "insufficient information".
- Be precise and structured. Always cite the file and page you used.

"""
    + FORMATTING_RULES
    + """

CONTEXT:
{context}

QUESTION:
{question}

ANSWER:
"""
)


def build_qna_chain(retriever) -> Runnable:
    """Free-text Q&A chain over policy documents."""
    llm = get_llm(temperature=0.1)

    def _retrieve_and_format(inputs: Dict[str, Any]) -> str:
        return format_docs_with_citations(retriever.invoke(inputs["question"]))

    return (
        {
            "context": RunnableLambda(_retrieve_and_format),
            "question": RunnableLambda(lambda x: x["question"]),
        }
        | QNA_PROMPT
        | llm
    )
