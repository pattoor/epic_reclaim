from __future__ import annotations

import json
import logging
import sys
import re

_SENSITIVE = re.compile(
    r"(password|passwd|token|secret|cookie|authorization|api[_-]?key|bot[_-]?token)",
    re.IGNORECASE,
)


def _redact_value(key: str, value: str) -> str:
    if _SENSITIVE.search(key):
        return "<redacted>"
    return value


class RedactingFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key, value in getattr(record, "context", {}).items():
            if isinstance(value, str):
                payload[key] = _redact_value(str(key), value)
            else:
                payload[key] = value
        return json.dumps(payload, ensure_ascii=True)


def configure_logging(level: int = logging.INFO) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(RedactingFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)
