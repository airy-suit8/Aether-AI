"""
logger.py — Task 16: Production Logging (with rotation)

Creates structured log files as specified in the internship plan:
  logs/requests.log  — all chat queries and responses
  logs/uploads.log   — document upload events
  logs/errors.log    — all errors across the application

Uses RotatingFileHandler to prevent log files from growing indefinitely.
Each file is capped at 5MB, with 5 backup copies kept.
"""

import logging
import sys
from pathlib import Path
from logging.handlers import RotatingFileHandler

# ── Create logs directory ─────────────────────────────────────────────────────

LOGS_DIR = Path(__file__).parent / "logs"
LOGS_DIR.mkdir(parents=True, exist_ok=True)

# ── Log format ────────────────────────────────────────────────────────────────

LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

formatter = logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT)

# Rotation config
MAX_BYTES = 5 * 1024 * 1024  # 5MB per file
BACKUP_COUNT = 5             # Keep 5 old copies


def _create_logger(name: str, log_file: str, level=logging.INFO) -> logging.Logger:
    """Create a logger that writes to a rotating file and stderr."""
    logger = logging.getLogger(name)
    logger.setLevel(level)

    # Prevent duplicate handlers on reload
    if logger.handlers:
        return logger

    # Rotating file handler (5MB max, 5 backups)
    file_handler = RotatingFileHandler(
        LOGS_DIR / log_file,
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

    return logger


# ── Named loggers (one per log file) ──────────────────────────────────────────

request_logger = _create_logger("requests", "requests.log")
upload_logger = _create_logger("uploads", "uploads.log")
error_logger = _create_logger("errors", "errors.log", level=logging.ERROR)
