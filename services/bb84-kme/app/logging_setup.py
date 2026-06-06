"""Centralised logging configuration (Phase 12-A) — KME-side mirror of the
webui-backend version. Stdlib-only.
"""
from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

DEFAULT_LOG_DIR = "/var/log/pqcqkd"
DEFAULT_MAX_BYTES = 10 * 1024 * 1024
DEFAULT_BACKUPS = 5
FMT = "%(asctime)s [%(levelname)s] %(name)s %(message)s"


def configure(service_name: str) -> logging.Logger:
    log_dir = Path(os.environ.get("LOG_DIR", DEFAULT_LOG_DIR))
    log_dir.mkdir(parents=True, exist_ok=True)

    level = os.environ.get("LOG_LEVEL", "INFO").upper()
    fmt = logging.Formatter(FMT)

    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()

    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    root.addHandler(sh)

    log_file = log_dir / f"{service_name}.log"
    fh = RotatingFileHandler(
        log_file,
        maxBytes=int(os.environ.get("LOG_MAX_BYTES", DEFAULT_MAX_BYTES)),
        backupCount=int(os.environ.get("LOG_BACKUPS", DEFAULT_BACKUPS)),
        encoding="utf-8",
    )
    fh.setFormatter(fmt)
    root.addHandler(fh)

    log = logging.getLogger(service_name)
    log.info("logging configured: stdout + %s", log_file)
    return log
