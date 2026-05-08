"""Centralised path / env configuration for the whole app."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv


# Directory layout (resolved at import, never hard-coded again elsewhere)
SRC_DIR: Path = Path(__file__).resolve().parent.parent
PROJECT_ROOT: Path = SRC_DIR.parent

DATA_DIR: Path = PROJECT_ROOT / "data"
CHROMA_ROOT: Path = PROJECT_ROOT / "chromadb"
UPLOAD_CHROMA_ROOT: Path = CHROMA_ROOT / "uploads"
ENV_FILE: Path = PROJECT_ROOT / ".env"


def load_env(env_file: Path = ENV_FILE) -> None:
    """Load .env once. Safe to call repeatedly."""
    if env_file.exists():
        load_dotenv(env_file)
    else:
        # Fall back to default search behaviour so the app still works
        # when .env lives elsewhere on a user's machine.
        load_dotenv()


def get_required_env(key: str) -> str:
    """Fetch an env var or raise a clear error suitable for surfacing in the UI."""
    load_env()
    value = os.getenv(key)
    if not value:
        raise RuntimeError(
            f"Missing required environment variable: {key}. "
            f"Add it to {ENV_FILE} and restart."
        )
    return value


def ensure_dirs() -> None:
    """Make sure all standard directories exist."""
    CHROMA_ROOT.mkdir(parents=True, exist_ok=True)
    UPLOAD_CHROMA_ROOT.mkdir(parents=True, exist_ok=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
