"""
Print row counts from the managed database, next to the Milestone 3 counts
when an ``old_row_counts.json`` is given::

    python -m src.db.row_counts [/migration/old_row_counts.json]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Dict, Optional

from src.core.config import load_env
from src.db.connection import connect


def new_counts() -> Dict[str, int]:
    with connect(vector=False) as conn:
        rows = conn.execute(
            """
            SELECT c.name, count(ch.chunk_id)
            FROM collections c LEFT JOIN chunks ch ON ch.collection_id = c.id
            GROUP BY c.name ORDER BY c.name
            """
        ).fetchall()
        uploads = conn.execute("SELECT count(*) FROM uploads").fetchone()[0]
    counts = {name: n for name, n in rows}
    counts["(uploads table)"] = uploads
    return counts


def print_side_by_side(old: Optional[Dict[str, int]], new: Dict[str, int]) -> bool:
    """Print the comparison; return True when every old collection matches."""
    old = old or {}
    names = sorted(set(old) | set(new), key=lambda n: (n.startswith("("), n.lower()))
    print(f"{'collection':<28} {'Chroma (M3)':>12} {'Postgres (M4)':>14}  match")
    print("-" * 64)
    ok = True
    for name in names:
        o, n = old.get(name), new.get(name, 0)
        if o is None:
            mark = "new"
        else:
            mark = "yes" if o == n else "NO"
            ok = ok and o == n
        print(f"{name:<28} {'-' if o is None else f'{o:,}':>12} {n:>14,}  {mark}")
    print("-" * 64)
    old_total = sum(old.values())
    new_total = sum(new.get(k, 0) for k in old)
    print(f"{'total (migrated)':<28} {old_total:>12,} {new_total:>14,}  {'yes' if ok else 'NO'}")
    return ok


def main(argv: list[str]) -> int:
    load_env()
    old = json.loads(Path(argv[0]).read_text(encoding="utf-8")) if argv else None
    ok = print_side_by_side(old, new_counts())
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
