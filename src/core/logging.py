"""Structured JSON logging, shared by the Streamlit process and the readiness
server.

Container Insights ships whatever each container prints on stdout into the
``ContainerLogV2`` table in Log Analytics as a single string column. Writing
one JSON object per line means that column can be parsed with ``parse_json()``
in KQL, which is what the Milestone 6 log-based 5xx metric and alert query on.
"""

from __future__ import annotations

import json
import logging
import sys
import time

_RESERVED = set(logging.LogRecord(None, 0, "", 0, "", None, None).__dict__) | {
    "message",
    "asctime",
}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": time.strftime(
                "%Y-%m-%dT%H:%M:%S", time.gmtime(record.created)
            )
            + f".{int(record.msecs):03d}Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key not in _RESERVED:
                payload[key] = value
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(level: int = logging.INFO) -> None:
    """Point the root logger at stdout with the JSON formatter.

    Idempotent — safe to call from both ``streamlit_app.py`` and
    ``src/health_server.py`` without producing duplicate handlers.
    """
    root = logging.getLogger()
    root.setLevel(level)
    if any(isinstance(h, logging.StreamHandler) and getattr(h, "_legalai_json", False) for h in root.handlers):
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    handler._legalai_json = True  # type: ignore[attr-defined]
    root.handlers = [handler]
