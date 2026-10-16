"""Connections to the managed PostgreSQL server."""

from __future__ import annotations

import os
from functools import lru_cache

import psycopg
from pgvector.psycopg import register_vector
from psycopg.conninfo import make_conninfo
from psycopg_pool import ConnectionPool

from src.core.config import get_required_env, load_env


def conninfo() -> str:
    """Connection string built from the environment; the password comes from Key Vault."""
    load_env()
    return make_conninfo(
        host=get_required_env("POSTGRES_HOST"),
        port=os.getenv("POSTGRES_PORT", "5432"),
        dbname=get_required_env("POSTGRES_DB"),
        user=get_required_env("POSTGRES_USER"),
        password=get_required_env("POSTGRES_PASSWORD"),
        sslmode=os.getenv("POSTGRES_SSLMODE", "require"),
        connect_timeout=10,
        application_name="legal-ai-hub",
    )


def connect(*, vector: bool = True) -> psycopg.Connection:
    """
    A standalone connection for CLI tools.

    ``vector=False`` is for the migration runner, which runs before the
    ``vector`` type exists.
    """
    conn = psycopg.connect(conninfo(), autocommit=True)
    if vector:
        register_vector(conn)
    return conn


@lru_cache(maxsize=1)
def get_pool() -> ConnectionPool:
    """Process-wide pool shared by every Streamlit session."""
    return ConnectionPool(
        conninfo(),
        min_size=1,
        max_size=5,
        kwargs={"autocommit": True},
        configure=register_vector,
        open=True,
    )
