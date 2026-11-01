"""
Readiness endpoint for Kubernetes, served on port 8080 beside Streamlit.

Liveness and readiness answer different questions, so they are different
checks:

* Liveness uses Streamlit's own ``/_stcore/health`` on port 8501. It only
  proves the server process is up and answering. A database outage must not
  fail it, or Kubernetes would restart every replica in a loop while the
  database is the thing that is broken.
* Readiness is ``/readyz`` here. It needs Streamlit to answer *and* the
  managed PostgreSQL server to accept a connection and return the applied
  migrations. When it fails the pod is taken out of the Service, so no user
  is routed to a replica that cannot reach its data, but the pod is not
  restarted.

Run with ``python -m src.health_server``.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Dict, Optional, Tuple

import psycopg

from src.core.logging import configure_logging
from src.db.connection import conninfo

logger = logging.getLogger("legalai.health")

PORT = int(os.getenv("HEALTH_PORT", "8080"))
STREAMLIT_HEALTH = f"http://127.0.0.1:{os.getenv('STREAMLIT_SERVER_PORT', '8501')}/_stcore/health"
# Probes from the kubelet arrive every few seconds; reuse one result briefly
# so they never pile up on the database.
CACHE_SECONDS = 2.0


class ReadinessCheck:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._conn: Optional[psycopg.Connection] = None
        self._checked_at = 0.0
        self._result: Optional[Tuple[bool, Dict[str, str]]] = None

    def _streamlit(self) -> None:
        with urllib.request.urlopen(STREAMLIT_HEALTH, timeout=2) as resp:
            if resp.status != 200:
                raise RuntimeError(f"HTTP {resp.status}")

    def _database(self) -> None:
        if self._conn is None or self._conn.closed:
            self._conn = psycopg.connect(conninfo(), autocommit=True, connect_timeout=3)
        try:
            applied = self._conn.execute("SELECT count(*) FROM schema_migrations").fetchone()[0]
        except Exception:
            self._conn.close()
            self._conn = None
            raise
        if applied == 0:
            raise RuntimeError("no migrations applied")

    def result(self) -> Tuple[bool, Dict[str, str]]:
        with self._lock:
            if self._result and time.monotonic() - self._checked_at < CACHE_SECONDS:
                return self._result
            checks: Dict[str, str] = {}
            for name, check in (("streamlit", self._streamlit), ("database", self._database)):
                try:
                    check()
                    checks[name] = "ok"
                except Exception as exc:
                    checks[name] = f"fail: {type(exc).__name__}: {exc}"[:200]
            self._result = (all(v == "ok" for v in checks.values()), checks)
            self._checked_at = time.monotonic()
            return self._result


READINESS = ReadinessCheck()


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path == "/readyz":
            self._readyz()
            return
        self.send_error(404)

    def do_POST(self) -> None:
        if self.path == "/debug/trigger-500":
            self._trigger_500()
            return
        self.send_error(404)

    def _readyz(self) -> None:
        ready, checks = READINESS.result()
        if not ready:
            logger.error(
                "readiness check failed",
                extra={"status_code": 503, "path": "/readyz", "checks": checks},
            )
        body = json.dumps({"ready": ready, "checks": checks}).encode()
        self.send_response(200 if ready else 503)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            # The kubelet gave up after timeoutSeconds; it already counted a failure.
            pass

    def _trigger_500(self) -> None:
        # Deliberate, demo-only 5xx: logs a JSON error record and returns HTTP
        # 500 without touching the database or Streamlit. Used to show the
        # log-based metric and alert firing on a controlled failure.
        logger.error(
            "controlled 5xx triggered for demo",
            extra={"status_code": 500, "path": "/debug/trigger-500"},
        )
        body = json.dumps({"triggered": True}).encode()
        self.send_response(500)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def log_message(self, format: str, *args) -> None:
        # One log line per probe every few seconds drowns the app's own logs.
        return


def main() -> None:
    configure_logging()
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
