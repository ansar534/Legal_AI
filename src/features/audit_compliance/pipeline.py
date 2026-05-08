"""
Compliance Audit Generator - pure RAG logic.

This module is intentionally Streamlit-free so it can be reused from a CLI,
notebook, or test suite. The matching ``page.py`` wires it into the app.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import Runnable, RunnableLambda
from pydantic import BaseModel, Field, ValidationError

from src.core.llm import STRUCTURED_OUTPUT_MODEL, get_llm
from src.core.retrievers import FORMATTING_RULES, format_docs_with_citations


# =========================================================
# Structured audit report schema
# =========================================================

class ComplianceGap(BaseModel):
    issue: str = Field(..., description="Concise statement of the compliance gap.")
    severity: str = Field(
        ..., description="One of: High, Medium, Low."
    )
    evidence: str = Field(..., description="Direct quote from the document.")
    filename: str = Field(..., description="Source file name.")
    page: Optional[int] = Field(
        None, description="Page number, if available."
    )


class Discrepancy(BaseModel):
    description: str = Field(..., description="What contradicts what.")
    conflicting_points: List[str] = Field(
        default_factory=list,
        description="The conflicting statements / clauses.",
    )
    evidence: str = Field(..., description="Quoted supporting text.")


class OutdatedProcedure(BaseModel):
    procedure: str = Field(..., description="The procedure that appears outdated.")
    why_outdated: str = Field(
        ..., description="Why it is outdated (e.g. superseded standard, year)."
    )
    evidence: str = Field(..., description="Quoted supporting text.")


class AuditReport(BaseModel):
    document_summary: str = Field(
        ..., description="2-4 sentence overview of the documents audited."
    )
    gaps: List[ComplianceGap] = Field(default_factory=list)
    discrepancies: List[Discrepancy] = Field(default_factory=list)
    outdated_procedures: List[OutdatedProcedure] = Field(default_factory=list)
    recommendations: List[str] = Field(default_factory=list)
    overall_compliance_rating: str = Field(
        ...,
        description=(
            "One of: Strong, Adequate, Needs Improvement, Critical. "
            "Reflects overall posture across the document set."
        ),
    )


# =========================================================
# Free-form Q&A chain
# =========================================================

QNA_PROMPT = ChatPromptTemplate.from_template(
    """
You are a senior compliance audit assistant.

Answer the user's question using ONLY the provided context.
If the answer is not in the context, say:
"I could not find sufficient information in the documents."

Always cite the file name and page number(s) you relied on.

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
    """Free-text Q&A chain: question -> retrieved context -> LLM answer."""
    llm = get_llm(temperature=0.2)

    def _retrieve_and_format(inputs: Dict[str, Any]) -> str:
        docs = retriever.invoke(inputs["question"])
        return format_docs_with_citations(docs)

    return (
        {
            "context": RunnableLambda(_retrieve_and_format),
            "question": RunnableLambda(lambda x: x["question"]),
        }
        | QNA_PROMPT
        | llm
    )


# =========================================================
# Structured audit-report chain
# =========================================================

# A fixed internal "question" used to drive retrieval for the report. The
# user does NOT type this -- they just click "Run Audit".
AUDIT_QUERY = (
    "compliance gaps risks discrepancies outdated procedures policy violations "
    "missing controls regulatory requirements obligations"
)


# A worked example shown to the model so it knows the exact JSON shape.
# Small / dense models like ``gpt-oss-20b`` are noticeably more reliable
# when given a one-shot example than when given a JSON schema alone.
_AUDIT_JSON_EXAMPLE = """\
{
  "document_summary": "Two-page security policy from Acme Corp. ...",
  "gaps": [
    {
      "issue": "No password rotation policy is defined.",
      "severity": "High",
      "evidence": "Quote from the document supporting this gap.",
      "filename": "acme_security_policy.pdf",
      "page": 2
    }
  ],
  "discrepancies": [
    {
      "description": "Section 3 contradicts Section 7 on data retention.",
      "conflicting_points": [
        "Section 3 says retain customer data for 1 year.",
        "Section 7 says retain customer data indefinitely."
      ],
      "evidence": "Quoted text showing both statements."
    }
  ],
  "outdated_procedures": [
    {
      "procedure": "References SHA-1 for password hashing.",
      "why_outdated": "SHA-1 is deprecated since 2017 (NIST SP 800-131A).",
      "evidence": "Quoted text mentioning SHA-1."
    }
  ],
  "recommendations": [
    "Adopt a 90-day password rotation policy.",
    "Reconcile Section 3 and Section 7 on retention."
  ],
  "overall_compliance_rating": "Needs Improvement"
}
"""


def _build_report_prompt() -> ChatPromptTemplate:
    """
    Build the audit prompt with a worked JSON example.

    We escape every literal ``{`` and ``}`` (using ``{{`` / ``}}``) so
    ChatPromptTemplate's f-string parser does not try to interpret them
    as input variables -- only ``{context}`` should be substituted.
    """
    safe_example = _AUDIT_JSON_EXAMPLE.replace("{", "{{").replace("}", "}}")

    return ChatPromptTemplate.from_messages(
        [
            (
                "system",
                """
You are a senior Compliance Audit Generator.

Use ONLY the provided context. Never invent facts, file names, or page numbers.

Your job is to streamline a compliance audit by surfacing:
1. Gaps         - missing controls, undocumented procedures, unmet requirements
2. Discrepancies - statements / clauses that contradict each other
3. Outdated procedures - references to superseded standards, repealed rules,
   stale dates, deprecated technology, or clearly old practices
4. Recommendations - concrete, actionable next steps

Output rules:
- Return ONLY a single JSON object. No markdown fences, no commentary
  before or after, no XML, no code blocks.
- Use the EXACT keys shown in the example below.
- "severity" must be one of: "High", "Medium", "Low".
- "overall_compliance_rating" must be one of: "Strong", "Adequate",
  "Needs Improvement", "Critical".
- Use direct quotes from the context for every "evidence" field.
- "page" must be an integer (or null if no page is available).
- If a section has no findings, return an empty list (do NOT fabricate).

EXAMPLE OUTPUT (match this structure exactly):

"""
                + safe_example,
            ),
            (
                "human",
                """
Audit task: Perform a complete compliance audit of the documents below.
Identify gaps, discrepancies, and outdated procedures. Cite filename and
page (when available) for every finding.

CONTEXT:
{context}

Now return the JSON object only.
""",
            ),
        ]
    )


# ---------------------------------------------------------------------------
# Robust JSON extractor
# ---------------------------------------------------------------------------

_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*\n?(.*?)\n?```", re.DOTALL)


def _extract_json_object(text: str) -> str:
    """
    Pull a single JSON object out of a possibly-noisy LLM response.

    Handles three common failure modes:
    1. The model wraps JSON in a ```json ... ``` markdown fence.
    2. The model emits prose before / after the JSON.
    3. The model emits multiple top-level objects (we take the first complete
       one with brace counting).
    """
    fence_match = _JSON_FENCE_RE.search(text)
    if fence_match:
        text = fence_match.group(1)

    start = text.find("{")
    if start == -1:
        raise ValueError("No '{' found in model output.")

    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]

    raise ValueError("No matching '}' found in model output.")


def _parse_audit_report(message: Any) -> AuditReport:
    """
    Robust parser used at the end of the audit chain.

    Falls back to :class:`PydanticOutputParser` if our own extraction fails,
    so the user gets a useful error message either way.
    """
    text = getattr(message, "content", str(message))

    try:
        json_text = _extract_json_object(text)
        data = json.loads(json_text)
        return AuditReport.model_validate(data)
    except (ValueError, json.JSONDecodeError, ValidationError) as primary_exc:
        # Last-ditch attempt: let LangChain's strict parser try with the
        # whole message; its error usually pinpoints the exact field.
        try:
            return PydanticOutputParser(
                pydantic_object=AuditReport
            ).parse(text)
        except Exception:
            preview = text[:600] + ("..." if len(text) > 600 else "")
            raise ValueError(
                "Audit report JSON could not be parsed.\n\n"
                f"First parse error: {primary_exc}\n\n"
                f"Model output (first 600 chars):\n{preview}"
            ) from primary_exc


def build_audit_report_chain(retriever) -> Runnable:
    """
    Returns a chain that produces an :class:`AuditReport` Pydantic object.

    Uses a stronger model (llama-3.3-70b) with Groq's JSON mode and a
    generous max_tokens budget. The default ``openai/gpt-oss-20b`` is
    known to silently produce empty output on this nested schema.

    Invoke with an empty dict::

        report = build_audit_report_chain(retriever).invoke({})
    """
    llm = get_llm(
        model=STRUCTURED_OUTPUT_MODEL,
        temperature=0.1,
        max_tokens=4096,
        json_mode=True,
    )
    prompt = _build_report_prompt()

    def _retrieve_for_audit(_: Dict[str, Any]) -> str:
        docs = retriever.invoke(AUDIT_QUERY)
        return format_docs_with_citations(docs)

    return (
        {"context": RunnableLambda(_retrieve_for_audit)}
        | prompt
        | llm
        | RunnableLambda(_parse_audit_report)
    )
