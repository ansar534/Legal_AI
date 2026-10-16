"""
Load the Milestone 3 Chroma export into PostgreSQL, keeping the original
chunk ids and embeddings::

    python -m src.db.import_chroma_export /migration/chroma_export.jsonl.gz

Safe to re-run: rows that already exist are skipped. Ends by printing the old
and new row counts side by side and exits non-zero if they differ.
"""

from __future__ import annotations

import base64
import gzip
import json
import sys
from pathlib import Path
from typing import Dict, List

import numpy as np

from src.core.config import load_env
from src.core.vectordb import _INSERT_SQL, chunk_row, ensure_collection
from src.db.connection import connect
from src.db.row_counts import new_counts, print_side_by_side

BATCH = 1000


def main(argv: List[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    export_path = Path(argv[0])
    old_counts_path = export_path.with_name("old_row_counts.json")
    load_env()

    collection_ids: Dict[str, int] = {}
    seen: Dict[str, int] = {}
    batch: List[tuple] = []

    with connect() as conn, gzip.open(export_path, "rt", encoding="utf-8") as f:
        def flush() -> None:
            with conn.transaction(), conn.cursor() as cur:
                cur.executemany(_INSERT_SQL, batch)
            batch.clear()

        for line in f:
            rec = json.loads(line)
            name = rec["collection"]
            if name not in collection_ids:
                collection_ids[name] = ensure_collection(name)
            embedding = np.frombuffer(base64.b64decode(rec["embedding"]), dtype="<f4")
            batch.append(
                chunk_row(collection_ids[name], rec["id"], rec["document"] or "", rec["metadata"], embedding)
            )
            seen[name] = seen.get(name, 0) + 1
            if len(batch) >= BATCH:
                flush()
                total = sum(seen.values())
                if total % 10_000 == 0:
                    print(f"  {total:,} rows read...", flush=True)
        if batch:
            flush()

    print(f"Read {sum(seen.values()):,} rows from {export_path.name}\n")
    if old_counts_path.exists():
        old = json.loads(old_counts_path.read_text(encoding="utf-8"))
    else:
        old = seen
    return 0 if print_side_by_side(old, new_counts()) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
