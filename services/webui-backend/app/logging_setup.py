"""Centralised logging configuration with rotating file output (Phase 12-A).

Replaces the previous `logging.basicConfig(...)` so every log line goes to:
  - stdout (Docker `docker logs` compatible — keeps existing behaviour)
  - LOG_DIR/<service>.log (RotatingFileHandler 10 MB × 5 backups)

The file output enables operators / browsers to download logs at any time via
`GET /api/logs/files` + `GET /api/logs/download/{service}` (Phase 12-C).

Environment:
  LOG_DIR    : directory for log files (default /var/log/pqcqkd)
  LOG_LEVEL  : logging level (default INFO)

Stdlib-only — no extra dependencies.
"""
from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

DEFAULT_LOG_DIR = "/var/log/pqcqkd"
DEFAULT_MAX_BYTES = 10 * 1024 * 1024   # 10 MB
DEFAULT_BACKUPS = 5
FMT = "%(asctime)s [%(levelname)s] %(name)s %(message)s"


def configure(service_name: str) -> logging.Logger:
    """Configure root logging (stdout + rotating file) and return the named logger."""
    log_dir = Path(os.environ.get("LOG_DIR", DEFAULT_LOG_DIR))
    log_dir.mkdir(parents=True, exist_ok=True)

    level = os.environ.get("LOG_LEVEL", "INFO").upper()
    fmt = logging.Formatter(FMT)

    root = logging.getLogger()
    root.setLevel(level)
    # Reset existing handlers to avoid duplicates on reload
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
    log.info("logging configured: stdout + %s (max %s bytes × %s)",
             log_file, DEFAULT_MAX_BYTES, DEFAULT_BACKUPS)
    return log


def list_log_files() -> list[dict[str, object]]:
    """Return metadata for every .log file under LOG_DIR.  Used by /api/logs/files."""
    log_dir = Path(os.environ.get("LOG_DIR", DEFAULT_LOG_DIR))
    if not log_dir.exists():
        return []
    out: list[dict[str, object]] = []
    for p in sorted(log_dir.glob("*.log*")):
        try:
            st = p.stat()
            out.append({"name": p.name, "size": st.st_size, "mtime": st.st_mtime})
        except FileNotFoundError:
            continue
    return out


def read_tail(service_name: str, lines: int = 200) -> str:
    """Return the last `lines` lines of <service>.log (latest rotation)."""
    log_dir = Path(os.environ.get("LOG_DIR", DEFAULT_LOG_DIR))
    path = log_dir / f"{service_name}.log"
    if not path.exists():
        return ""
    with path.open("r", encoding="utf-8", errors="replace") as f:
        data = f.readlines()
    return "".join(data[-lines:])
