"""Lightweight, framework-agnostic data classes shared by core + features."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from pydantic import BaseModel


@dataclass
class DataSource:
    """
    Resolved output of `core.ui.source_picker`.

    Tells a feature exactly which files to load, which Chroma collection
    to use, and where on disk that collection lives.
    """

    files: List[Path]
    collection_name: str
    persist_path: Path
    is_upload: bool = False
    label: str = ""

    def signature(self) -> str:
        """Stable identity used as a session_state cache key."""
        names = sorted(p.name for p in self.files)
        return f"{self.collection_name}::{'|'.join(names)}"


class Citation(BaseModel):
    """Generic source reference reusable by any feature's structured output."""

    filename: str
    page: Optional[int] = None
    quote: str = ""
