"""ETSI GS QKD 004 V2.1.1: the status codes and the shared spec file.

The spec facts live in ONE file, `etsi004SpecV211.json`, which the browser's
simulator (/protocol-lab) also imports. The frontend image can only see its own
directory, so the file sits there; this image is built from the repository root
and COPYs it in (Dockerfile). Its path comes from ETSI004_SPEC_FILE and nothing
else: there is no fallback path, because a second copy would be a second
source of truth, and a missing file must fail the build, not a request.

The status enum below is this project's own naming of V2.1.1's codes 0-8. It
is asserted against the spec file at import, so the two cannot drift.
"""
from __future__ import annotations

import json
import os
from enum import IntEnum, StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Any


class Etsi004Status(IntEnum):
    """ETSI GS QKD 004 V2.1.1, clause 6.1, Table 2, Status. Names are ours."""

    SUCCESSFUL = 0
    PEER_NOT_CONNECTED = 1
    INSUFFICIENT_KEY = 2
    PEER_APP_NOT_CONNECTED = 3
    NO_QKD_CONNECTION = 4
    KSID_IN_USE = 5
    TIMEOUT = 6
    QOS_NOT_MET = 7
    METADATA_TOO_SMALL = 8


class StreamState(StrEnum):
    ABSENT = "ABSENT"
    PENDING_PEER = "PENDING_PEER"
    ESTABLISHED = "ESTABLISHED"
    CLOSING = "CLOSING"
    CLOSED = "CLOSED"


@lru_cache(maxsize=1)
def load_spec() -> dict[str, Any]:
    path = os.environ.get("ETSI004_SPEC_FILE")
    if not path:
        raise RuntimeError(
            "ETSI004_SPEC_FILE is not set. It must point at etsi004SpecV211.json "
            "(the Dockerfile sets it; tests/conftest.py sets it for host runs).")
    spec = json.loads(Path(path).read_text(encoding="utf-8"))
    codes = {s["id"]: s["code"] for s in spec["status_codes"]}
    ours = {m.name: m.value for m in Etsi004Status}
    if codes != ours:
        raise RuntimeError(f"Etsi004Status disagrees with {path}: {codes} vs {ours}")
    if spec["version"] != "V2.1.1":
        raise RuntimeError(f"{path} describes {spec['version']}, not V2.1.1")
    if spec["states"] != [s.value for s in StreamState]:
        raise RuntimeError(f"StreamState disagrees with {path}")
    return spec


def uint32_max() -> int:
    return int(load_spec()["uint32_max"])


def binding() -> dict[str, Any]:
    return load_spec()["binding"]
