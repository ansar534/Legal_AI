"""
Apply pending SQL migrations from ``migrations/`` in filename order.

Run inside the app container::

    docker compose run --rm app python -m src.db.migrate
"""

from __future__ import annotations

import sys
from typing import List

from src.core.config import MIGRATIONS_DIR
from src.db.connection import connect


def apply_migrations() -> List[str]:
    """Apply every migration not yet recorded in ``schema_migrations``."""
    applied_now: List[str] = []
    with connect(vector=False) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version    TEXT        PRIMARY KEY,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        done = {row[0] for row in conn.execute("SELECT version FROM schema_migrations")}
        for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
            if path.stem in done:
                continue
            with conn.transaction():
                conn.execute(path.read_text(encoding="utf-8"))
                conn.execute(
                    "INSERT INTO schema_migrations (version) VALUES (%s)", (path.stem,)
                )
            applied_now.append(path.stem)
    return applied_now


def main() -> int:
    applied = apply_migrations()
    if applied:
        for version in applied:
            print(f"applied {version}")
    else:
        print("database is up to date")
    with connect(vector=False) as conn:
        tables = conn.execute(
            """
            SELECT table_name FROM information_schema.tables
            WHERE table_schema = 'public' ORDER BY table_name
            """
        ).fetchall()
    print("tables: " + ", ".join(t[0] for t in tables))
    return 0


if __name__ == "__main__":
    sys.exit(main())
