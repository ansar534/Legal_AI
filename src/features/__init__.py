"""
Plug-in registry for the Legal AI Hub.

Adding a new feature is mechanical:

1. Create ``src/features/<name>/`` with ``pipeline.py`` (no Streamlit imports)
   and ``page.py`` exporting ``SPEC: FeatureSpec`` and a ``render()`` function.
2. Append ``SPEC`` to the ``FEATURES`` list at the bottom of this file.
3. ``streamlit_app.py`` will pick it up automatically via ``st.navigation``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Optional

from src.core.config import CHROMA_ROOT


@dataclass
class FeatureSpec:
    """Everything `streamlit_app.py` and `core.ui.source_picker` need to know."""

    key: str
    title: str
    icon: str
    page_render: Callable[[], None]
    default_collection: str
    data_folder: Optional[Path] = None
    supported_uploads: List[str] = field(default_factory=lambda: ["pdf"])
    description: str = ""
    # Optional override for where the feature's persistent Chroma collection
    # lives on disk. When ``None`` the shared ``chromadb/`` directory is used.
    # ``litigation`` keeps its existing ``vector_store/litigation_support`` so
    # previously-built embeddings are reused.
    custom_persist_path: Optional[Path] = None

    @property
    def collection_path(self) -> Path:
        """Where the feature's *default* (non-upload) Chroma collection lives."""
        return self.custom_persist_path or CHROMA_ROOT


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------
# Each feature lives under src/features/<name>/ and exports `SPEC: FeatureSpec`
# from its `page.py`. Adding a new feature is: drop a folder, append its SPEC
# to the FEATURES list below. The streamlit_app.py entry point picks it up
# via st.navigation, no other code changes required.
#
# These imports rely on Python's standard handling of partial-module imports:
# each child page.py imports `FeatureSpec` from this module, which is already
# defined above by the time these lines execute.
from src.features.audit_compliance.page import SPEC as _AUDIT_SPEC
from src.features.contract_qna.page import SPEC as _CONTRACT_QNA_SPEC
from src.features.contract_risk.page import SPEC as _CONTRACT_RISK_SPEC
from src.features.litigation.page import SPEC as _LITIGATION_SPEC
from src.features.policies_qna.page import SPEC as _POLICIES_SPEC
from src.features.regulations_rag.page import SPEC as _REGULATIONS_SPEC


FEATURES: List[FeatureSpec] = [
    _AUDIT_SPEC,
    _CONTRACT_QNA_SPEC,
    _CONTRACT_RISK_SPEC,
    _POLICIES_SPEC,
    _LITIGATION_SPEC,
    _REGULATIONS_SPEC,
]
