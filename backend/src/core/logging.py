"""
core/logging.py — Task 16: Production Logging (with rotation)

Three named loggers, one file each, in settings.log_dir:
  requests.log  — all chat queries and responses
  uploads.log   — document upload events
  errors.log    — all errors and warnings across the application

Importing this module creates no folder and opens no file: setup_logging() does that, and the
app calls it from its lifespan hook. Each file rotates at 5MB, with 5 backup copies kept.
"""

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
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

_FILES = [
    (request_logger, "requests.log", logging.INFO),
    (upload_logger, "uploads.log", logging.INFO),
    (error_logger, "errors.log", logging.WARNING),
]


def setup_logging(log_dir: Path) -> None:
    """Attach a rotating file handler and a stderr handler to each logger. Safe to call twice."""
    log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT)
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
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

        # Stderr handler (so logs also appear in the terminal)
        stream_handler = logging.StreamHandler(sys.stderr)
        stream_handler.setFormatter(formatter)
        logger.addHandler(stream_handler)
