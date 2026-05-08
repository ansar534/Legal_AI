"""Contract Q&A - Rights / Obligations / Risks / Exceptions chain."""

from __future__ import annotations

from typing import Any, Dict

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import Runnable, RunnableLambda

from src.core.llm import get_llm
from src.core.retrievers import FORMATTING_RULES, format_docs_with_citations


CONTRACT_QNA_PROMPT = ChatPromptTemplate.from_template(
    """
You are a Contract Analysis Assistant.

Use ONLY the provided contract context.

Structure your answer using these four sections (use a section even if empty
to make the structure obvious):

1. Rights
2. Obligations
3. Risks
4. Exceptions

After the four sections, list the source files and clauses you relied on.

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
    llm = get_llm(temperature=0.1)

    def _retrieve_and_format(inputs: Dict[str, Any]) -> str:
        return format_docs_with_citations(retriever.invoke(inputs["question"]))

    return (
        {
            "context": RunnableLambda(_retrieve_and_format),
            "question": RunnableLambda(lambda x: x["question"]),
        }
        | CONTRACT_QNA_PROMPT
        | llm
    )
