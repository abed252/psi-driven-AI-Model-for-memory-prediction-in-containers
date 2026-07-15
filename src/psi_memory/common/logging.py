"""Structured logging setup used by every entry point."""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path


class JsonLinesHandler(logging.FileHandler):
    """Writes one JSON object per log record, for machine-readable logs."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            payload = {
                "ts": time.time(),
                "level": record.levelname,
                "logger": record.name,
                "message": record.getMessage(),
            }
            self.stream.write(json.dumps(payload) + "\n")
            self.flush()
        except Exception:
            self.handleError(record)


def setup_logging(level: str = "INFO", jsonl_path: Path | None = None) -> None:
    """Configure console logging (Rich if available) plus optional JSONL file."""
    handlers: list[logging.Handler] = []
    try:
        from rich.logging import RichHandler

        handlers.append(RichHandler(rich_tracebacks=True, show_path=False))
        fmt = "%(message)s"
    except ImportError:
        handlers.append(logging.StreamHandler())
        fmt = "%(asctime)s %(levelname)s %(name)s: %(message)s"

    if jsonl_path is not None:
        jsonl_path.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(JsonLinesHandler(jsonl_path, encoding="utf-8"))

    logging.basicConfig(level=level, format=fmt, handlers=handlers, force=True)
