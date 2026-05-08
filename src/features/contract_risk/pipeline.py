"""
Contract Risk Analyzer - hybrid pipeline.

The risky-clauses **knowledge base** (PDF + CSV under data/Contract_Risk/)
is always available. The user MAY also upload their own contract; when they
do, every question is answered against BOTH the KB and the uploaded contract,
so the assistant can say e.g. "your contract has clause X which matches
risky pattern Y from the KB".
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from langchain_core.documents import Document
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import Runnable, RunnableLambda

from src.core.llm import get_llm
from src.core.retrievers import FORMATTING_RULES


CONTRACT_RISK_PROMPT = ChatPromptTemplate.from_template(
    """
You are a Contract Risk Analysis AI.

You have access to TWO sources of context:

1. RISKY CLAUSE KNOWLEDGE BASE - a curated dataset of clause patterns and
   their risk profiles.
2. USER CONTRACT (optional) - the contract the user has uploaded for review.
   This block will say "(none)" when no contract has been uploaded.

When a user contract is provided, cross-reference its clauses against the
risk knowledge base and call out matches by name. When no contract is
provided, answer purely from the knowledge base.

Always structure your answer as:
1. Risk Summary
2. High Risk Clauses (with quotes + source)
3. Medium Risk Clauses (with quotes + source)
4. Low Risk Clauses
5. Recommendations

If the answer is not present in either context, say so explicitly.

"""
    + FORMATTING_RULES
    + """

================ RISKY CLAUSE KNOWLEDGE BASE ================
{kb_context}

================ USER CONTRACT ================
{contract_context}

================ QUESTION ================
{question}

ANSWER:
"""
)


def _format_docs(docs: List[Document], label: str) -> str:
    if not docs:
        return "(none)"
    blocks = []
    for d in docs:
        filename = d.metadata.get("filename", label)
        page = d.metadata.get("page")
        source_type = d.metadata.get("source_type", "")
        suffix = f" [{source_type}]" if source_type else ""
        header = f"FILE: {filename}{suffix}"
        if isinstance(page, int):
            header += f"\nPAGE: {page + 1}"
        blocks.append(f"{header}\n\n{d.page_content}")
    return "\n\n------------------\n\n".join(blocks)


def build_chain(kb_retriever, contract_retriever=None) -> Runnable:
    """
    Build the contract-risk chain.

    Args:
        kb_retriever: retriever over the risky-clauses knowledge base
            (always required).
        contract_retriever: optional retriever over the user's uploaded
            contract. When provided, retrieved chunks are passed to the LLM
            in a separate USER CONTRACT block so it can cross-reference.
    """
    llm = get_llm(temperature=0.1)

    def _retrieve(inputs: Dict[str, Any]) -> Dict[str, str]:
        question = inputs["question"]
        kb_docs = kb_retriever.invoke(question)
        kb_text = _format_docs(kb_docs, label="kb")

        if contract_retriever is not None:
            contract_docs = contract_retriever.invoke(question)
            contract_text = _format_docs(contract_docs, label="user_contract")
        else:
            contract_text = "(none)"

        return {
            "kb_context": kb_text,
            "contract_context": contract_text,
            "question": question,
        }

    return RunnableLambda(_retrieve) | CONTRACT_RISK_PROMPT | llm
