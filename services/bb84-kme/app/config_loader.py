"""YAML-based central parameter loader with hot-reload.

Single source of truth: config/qkd_params.yaml (mounted into containers as
/etc/pqcqkd/qkd_params.yaml).  Any module that needs a numeric tunable MUST
read it via `params()` — literal numbers are forbidden in services/bb84-kme/app
and enforced by tests/test_no_hardcoded_params.py.

Provenance of defaults: see comments in config/qkd_params.yaml.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

log = logging.getLogger(__name__)

CONFIG_PATH = Path(os.environ.get("QKD_PARAMS_FILE", "/etc/pqcqkd/qkd_params.yaml"))


@dataclass(slots=True)
class _CachedParams:
    raw: dict[str, Any] = field(default_factory=dict)
    mtime: float = 0.0
    lock: threading.RLock = field(default_factory=threading.RLock)
    listeners: list = field(default_factory=list)


_cache = _CachedParams()


def _read_file() -> dict[str, Any]:
    if not CONFIG_PATH.exists():
        log.warning("Config file %s missing — using empty defaults", CONFIG_PATH)
        return {}
    with CONFIG_PATH.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def reload() -> dict[str, Any]:
    """Force reload from disk and notify listeners."""
    with _cache.lock:
        _cache.raw = _read_file()
        try:
            _cache.mtime = CONFIG_PATH.stat().st_mtime
        except FileNotFoundError:
            _cache.mtime = 0.0
        listeners = list(_cache.listeners)
    for cb in listeners:
        try:
            cb(_cache.raw)
        except Exception as e:    # pragma: no cover
            log.warning("config listener error: %s", e)
    return _cache.raw


def params() -> dict[str, Any]:
    """Get current cached params, reloading if file changed on disk."""
    with _cache.lock:
        try:
            mt = CONFIG_PATH.stat().st_mtime
        except FileNotFoundError:
            mt = 0.0
        if mt != _cache.mtime:
            return reload()
        return _cache.raw


def get(path: str, default: Any = None) -> Any:
    """Dotted path lookup e.g. `physical.detector_efficiency`."""
    cur: Any = params()
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return default
        cur = cur[part]
    return cur


def subscribe(callback) -> None:
    """Register a callable(dict) invoked on every reload."""
    with _cache.lock:
        _cache.listeners.append(callback)


def start_watchdog(poll_interval_s: float = 1.0) -> threading.Thread:
    """Background poller — simpler than `watchdog` package and works in containers."""
    def _loop():
        while True:
            try:
                params()       # implicit reload on mtime change
            except Exception as e:  # pragma: no cover
                log.warning("watchdog poll error: %s", e)
            time.sleep(poll_interval_s)
    t = threading.Thread(target=_loop, name="config-watchdog", daemon=True)
    t.start()
    return t


# convenience accessors (kept narrow on purpose — the rest use get(path))

def env_override(path: str, env_name: str, cast=str, default=None):
    """Allow an env var to override the YAML value (for legacy compatibility)."""
    v = os.environ.get(env_name)
    if v is not None and v != "":
        try:
            return cast(v)
        except ValueError:
            return default if default is not None else get(path, default)
    return get(path, default)
