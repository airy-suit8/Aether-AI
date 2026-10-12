"""
core/logging.py — Task 16: Production Logging (with rotation)

Three named loggers, one file each, in settings.log_dir:
  requests.log  — all chat queries and responses
  uploads.log   — document upload events
  errors.log    — all errors and warnings across the application

The files are structured (S10): one JSON object per line, with the time, level, logger, the
request id the client was given (X-Request-ID), the event name and its fields. log_event()
writes one. Fields carry ids, counts and settings, never the text of a question. The terminal
gets the same lines in a readable form.

Importing this module creates no folder and opens no file: setup_logging() does that, and the
app calls it from its lifespan hook. Each file rotates at 5MB, with 5 backup copies kept.
"""

import json
import logging
import sys
from contextvars import ContextVar
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional

DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# Rotation config
MAX_BYTES = 5 * 1024 * 1024  # 5MB per file
BACKUP_COUNT = 5             # Keep 5 old copies

# ── Named loggers (one per log file) ──────────────────────────────────────────
# Under "aether." on purpose: a logger named plain "requests" is the HTTP library's own, which
# already carries a handler, so setup_logging() skipped it and requests.log was never written.

request_logger = logging.getLogger("aether.requests")
upload_logger = logging.getLogger("aether.uploads")
error_logger = logging.getLogger("aether.errors")

# The id of the request being served; set by the request middleware (src/api/middleware.py)
request_id: ContextVar[Optional[str]] = ContextVar("aether_request_id", default=None)


def log_event(logger: logging.Logger, event: str, level: int = logging.INFO, exc_info=False, **fields) -> None:
    """Write one structured line: the event name and its fields (ids, counts, settings; no question text)."""
    logger.log(level, event, extra={"fields": fields}, exc_info=exc_info)


class JsonFormatter(logging.Formatter):
    """One JSON object per line. Escaping is JSON's, so a value cannot forge a second line."""

    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "time": self.formatTime(record, DATE_FORMAT),
            "level": record.levelname,
            "logger": record.name,
            "request_id": request_id.get(),
            "event": record.getMessage(),
            **getattr(record, "fields", {}),
        }
        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry, ensure_ascii=False, default=str)


class TextFormatter(logging.Formatter):
    """The terminal's form of the same line: time | level | logger | event key=value ..."""

    def format(self, record: logging.LogRecord) -> str:
        fields = {"request_id": request_id.get(), **getattr(record, "fields", {})}
        pairs = " ".join(f"{k}={json.dumps(v, ensure_ascii=False, default=str)}" for k, v in fields.items() if v is not None)
        line = f"{self.formatTime(record, DATE_FORMAT)} | {record.levelname:<8} | {record.name} | {record.getMessage()} {pairs}".rstrip()
        if record.exc_info:
            line += "\n" + self.formatException(record.exc_info)
        return line


_FILES = [
    (request_logger, "requests.log", logging.INFO),
    (upload_logger, "uploads.log", logging.INFO),
    (error_logger, "errors.log", logging.WARNING),
]


def setup_logging(log_dir: Path) -> None:
    """Attach a rotating file handler and a stderr handler to each logger. Safe to call twice."""
    log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    for logger, log_file, level in _FILES:
        logger.setLevel(level)
        # Prevent duplicate handlers on reload
        if logger.handlers:
            continue

        file_handler = RotatingFileHandler(
            log_dir / log_file,
            maxBytes=MAX_BYTES,
            backupCount=BACKUP_COUNT,
            encoding="utf-8",
        )
        file_handler.setFormatter(JsonFormatter())
        logger.addHandler(file_handler)

        # Stderr handler (so logs also appear in the terminal)
        stream_handler = logging.StreamHandler(sys.stderr)
        stream_handler.setFormatter(TextFormatter())
        logger.addHandler(stream_handler)
