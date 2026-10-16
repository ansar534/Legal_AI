"""
Export the Milestone 3 Chroma stores to a portable file for the PostgreSQL import.

Runs on the machine that still holds the old ``chromadb/`` and
``vector_store/`` folders. It needs ``chromadb``, which the app image no
longer installs::

    python tools/export_chroma.py

Writes ``migration/chroma_export.jsonl.gz`` (one chunk per line, embeddings
included so nothing is re-embedded) and ``migration/old_row_counts.json``.
The import side is ``python -m src.db.import_chroma_export``.
"""

from __future__ import annotations

import base64
import gzip
import json
import sys
from pathlib import Path

import chromadb
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = PROJECT_ROOT / "migration"
BATCH = 2000


def chroma_roots() -> list[Path]:
    """Every directory that holds a Milestone 3 Chroma database."""
    candidates = [PROJECT_ROOT / "chromadb", PROJECT_ROOT / "vector_store" / "litigation_support"]
    uploads = PROJECT_ROOT / "chromadb" / "uploads"
    if uploads.exists():
        candidates.extend(sorted(p for p in uploads.iterdir() if p.is_dir()))
    return [p for p in candidates if (p / "chroma.sqlite3").exists()]


def main() -> int:
    OUT_DIR.mkdir(exist_ok=True)
    export_path = OUT_DIR / "chroma_export.jsonl.gz"
    counts: dict[str, int] = {}

    with gzip.open(export_path, "wt", encoding="utf-8") as out:
        for root in chroma_roots():
            client = chromadb.PersistentClient(path=str(root))
            for col in client.list_collections():
                name = col if isinstance(col, str) else col.name
                if name in counts:
                    raise SystemExit(f"Collection {name} exists in more than one store")
                collection = client.get_collection(name)
                total = collection.count()
                written = 0
                for offset in range(0, total, BATCH):
                    page = collection.get(
                        limit=BATCH,
                        offset=offset,
                        include=["documents", "metadatas", "embeddings"],
                    )
                    for cid, doc, meta, emb in zip(
                        page["ids"], page["documents"], page["metadatas"], page["embeddings"]
                    ):
                        vector = np.asarray(emb, dtype="<f4")
                        out.write(
                            json.dumps(
                                {
                                    "collection": name,
                                    "id": cid,
                                    "document": doc,
                                    "metadata": meta or {},
                                    "embedding": base64.b64encode(vector.tobytes()).decode("ascii"),
                                },
                                ensure_ascii=False,
                            )
                            + "\n"
                        )
                        written += 1
                if written != total:
                    raise SystemExit(f"{name}: exported {written} of {total} rows")
                counts[name] = total
                print(f"{name:<24} {total:>8,}  from {root.relative_to(PROJECT_ROOT)}")

    (OUT_DIR / "old_row_counts.json").write_text(
        json.dumps(dict(sorted(counts.items())), indent=2) + "\n", encoding="utf-8"
    )
    print(f"{'total':<24} {sum(counts.values()):>8,}")
    print(f"wrote {export_path.relative_to(PROJECT_ROOT)} ({export_path.stat().st_size / 1e6:.1f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
