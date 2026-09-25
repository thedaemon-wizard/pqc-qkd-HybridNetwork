"""Every `etsi004.*` key in config/qkd_params.yaml is read by the KME itself.

tests/test_every_config_key_is_read_by_something.py accepts a reader anywhere
in the repository, by dotted path or by leaf name -- and the browser's
Protocol Lab simulator has its own `max_streams`-like names. That would call a
KME knob live because a TypeScript file happens to share its leaf name. These
keys configure the KME's 004 endpoint, so the reader must be in
services/bb84-kme/app, by the full dotted path, through `require` (a missing
key fails loudly rather than falling back).
"""
from __future__ import annotations

from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]


def test_every_etsi004_key_is_required_by_the_kme():
    keys = yaml.safe_load((REPO / "config/qkd_params.yaml").read_text())["etsi004"]
    src = "\n".join(p.read_text() for p in (REPO / "services/bb84-kme/app").glob("*.py"))
    missing = [k for k in keys if f'require("etsi004.{k}")' not in src]
    assert not missing, f"etsi004 keys the KME never requires: {missing}"
