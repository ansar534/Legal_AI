"""
Legal AI Hub - Streamlit entry point.

Run with::

    cd Legal_AI_Project
    streamlit run streamlit_app.py

Pages are discovered automatically from ``src/features/__init__.py``'s
``FEATURES`` registry. To add a feature, drop a new folder under
``src/features/<name>/`` (with ``pipeline.py`` + ``page.py``) and append its
``SPEC`` to that registry.
"""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st


# Make ``import src.*`` work when running ``streamlit run streamlit_app.py``.
_PROJECT_ROOT = Path(__file__).resolve().parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


st.set_page_config(
    page_title="Legal AI Hub",
    page_icon=":material/balance:",
    layout="wide",
)


# Imported AFTER set_page_config so any cached @st.cache_resource calls
# triggered at import time are safe.
from src.core.config import ensure_dirs, load_env  # noqa: E402
from src.features import FEATURES  # noqa: E402


load_env()
ensure_dirs()


def _build_pages():
    pages = []
    for spec in FEATURES:
        pages.append(
            st.Page(
                spec.page_render,
                title=spec.title,
                icon=spec.icon,
                url_path=spec.key,
            )
        )
    return pages


nav = st.navigation({"Tools": _build_pages()})
nav.run()
