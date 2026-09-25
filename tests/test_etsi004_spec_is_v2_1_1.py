"""The KME reads the ETSI GS QKD 004 spec file the browser reads, and no other.

tests/test_protocol_lab_etsi_spec.py pins what the shared file says. This pins
how the KME gets it: through ETSI004_SPEC_FILE only, copied into the image and
loaded at build time, with the status enum checked against it on load -- and
the browser simulator importing the same file, so the two cannot describe
different editions.
"""
from __future__ import annotations

import importlib
import os
import re
from pathlib import Path

import pytest
from conftest import load_service_app

REPO = Path(__file__).resolve().parents[1]
SPEC_REL = "services/webui-frontend/src/lib/sim/etsi004SpecV211.json"

load_service_app("bb84-kme", "bb84_kme_app")
spec_mod = importlib.import_module("bb84_kme_app.etsi004_spec")


def test_the_status_enum_is_the_files():
    spec = spec_mod.load_spec()
    assert spec["version"] == "V2.1.1"
    assert {m.name: m.value for m in spec_mod.Etsi004Status} == \
        {s["id"]: s["code"] for s in spec["status_codes"]}
    assert spec_mod.Etsi004Status.PEER_NOT_CONNECTED == 1
    assert spec_mod.Etsi004Status.TIMEOUT == 6
    assert spec_mod.uint32_max() == 2**32 - 1


def test_there_is_no_fallback_path(monkeypatch):
    monkeypatch.delenv("ETSI004_SPEC_FILE")
    spec_mod.load_spec.cache_clear()
    try:
        with pytest.raises(RuntimeError, match="ETSI004_SPEC_FILE"):
            spec_mod.load_spec()
    finally:
        spec_mod.load_spec.cache_clear()
    src = (REPO / "services/bb84-kme/app/etsi004_spec.py").read_text()
    assert "etsi004SpecV211.json\"" not in src.replace("`etsi004SpecV211.json`", "")


def test_the_image_carries_the_file_and_loads_it_at_build_time():
    df = (REPO / "services/bb84-kme/Dockerfile").read_text()
    m = re.search(rf"^COPY {re.escape(SPEC_REL)} (\S+)$", df, re.M)
    assert m, "the KME image does not COPY the shared spec file"
    dest = m.group(1)
    env = re.search(r"^ENV ETSI004_SPEC_FILE=(\S+)$", df, re.M)
    assert env, "ETSI004_SPEC_FILE is not set in the image"
    workdir = re.search(r"^WORKDIR (\S+)$", df, re.M).group(1)
    assert env.group(1) == os.path.normpath(os.path.join(workdir, dest))
    assert df.index(m.group(0)) < df.index("load_spec()"), "loaded before it is copied"


def test_the_browser_simulator_imports_the_same_file():
    sim = (REPO / "services/webui-frontend/src/lib/sim/protocolLab/etsi004.ts").read_text()
    assert re.search(r'from\s+"\.\./etsi004SpecV211\.json"', sim)
