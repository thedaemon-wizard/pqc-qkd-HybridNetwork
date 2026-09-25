"""Commit messages and GitHub text are scanned with the SAME matchers as the tree.

The tracked-content guards (test_repo_is_publication_ready.py and
test_private_files_have_a_safe_harbour.py) never read commit messages or pull
request bodies, which are published too. The CI message check and the GitHub
surface audit therefore kept their own literal pattern lists, and those lists
drifted: the audit's list lacked the one product name the tooling signs with,
and neither list could look for the private file names, because writing them
into a script would disclose them.

scripts/scan_published_text.py closes that by importing the tree guards'
matchers. These tests pin the three properties that make it worth having: it
actually fires, it never echoes what it found (its output lands in public CI
logs), and the two callers really use it.
"""
from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import re
import sys
from contextlib import redirect_stdout
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "scan_published_text.py"
CI = ROOT / ".github" / "workflows" / "ci.yml"
AUDIT = ROOT / "scripts" / "audit_github_surface.sh"


def _scanner():
    spec = importlib.util.spec_from_file_location("scan_published_text", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# A stand-in stem registered as a numbered note for these tests only, so the
# scanner is exercised end to end without this file writing a real shape.
_PROBE_STEM = "zzprobenote"
_SHAPES = (f"see {_PROBE_STEM}7 for the request", f"as planned in {_PROBE_STEM}0.md")


@pytest.fixture
def probe_registered(monkeypatch):
    """Make the scanner's private-matcher module treat the probe stem as a note."""
    mod = _scanner()
    real_load = mod._load

    def load(name):
        m = real_load(name)
        if name == "test_private_files_have_a_safe_harbour.py":
            digests = m._NUMBERED_NOTE_STEM_DIGESTS | {
                hashlib.sha256(_PROBE_STEM.encode()).hexdigest()}
            monkeypatch.setattr(m, "_NUMBERED_NOTE_STEM_DIGESTS", digests)
            real = m._names_a_numbered_note
            monkeypatch.setattr(m, "_names_a_numbered_note",
                                lambda text, d=digests: real(text, d))
        return m

    monkeypatch.setattr(mod, "_load", load)
    return mod


def _run(records: list[dict], mod=None) -> tuple[int, str]:
    mod = mod or _scanner()
    payload = "\n".join(json.dumps(r) for r in records)
    buf = io.StringIO()
    old = sys.stdin
    sys.stdin = io.StringIO(payload)
    try:
        with redirect_stdout(buf):
            code = mod.main(["--jsonl"])
    finally:
        sys.stdin = old
    return code, buf.getvalue()


def test_the_scanner_fires_on_each_category(probe_registered):
    samples = [
        {"id": "shape-a", "text": _SHAPES[0]},
        {"id": "shape-b", "text": _SHAPES[1]},
        {"id": "attribution", "text": "Generated with an assistant"},
        {"id": "address", "text": "reachable at 203.0.113.9"},  # PUBGUARD-ALLOW
    ]
    code, out = _run(samples, probe_registered)
    assert code == 1, out
    for s in samples:
        assert f"{s['id']}:" in out, f"{s['id']} was not reported:\n{out}"


def test_the_scanner_is_quiet_on_ordinary_text():
    code, out = _run([
        {"id": "a", "text": "Reorder the planning notes in docs/roadmap.md"},
        {"id": "b", "text": "WebLLM is a library name, 10.30.0.21 is a lab address"},
        {"id": "c", "text": "SHA256 over IPv4 and ETSI 014 v2 in round 3"},
    ])
    assert code == 0, out


def test_the_report_never_echoes_what_it_matched(probe_registered):
    """CI logs of a public repository are public; an echo republishes."""
    code, out = _run([{"id": "r1", "text": _SHAPES[0]},
                      {"id": "r2", "text": _SHAPES[1]}], probe_registered)
    assert code == 1, out
    assert _PROBE_STEM not in out, "the report printed the matched token"


def test_no_note_stem_or_accepted_commit_is_written_into_the_tree_tools():
    """The shapes live only as digests; accepted commits come from outside."""
    for path in (SCRIPT, AUDIT, CI):
        text = path.read_text(encoding="utf-8")
        assert not re.search(r"--accept-commit [0-9a-f]{7,}", text), path
        assert not re.search(r"\b[0-9a-f]{12,40}\b", text.split("gitleaks")[0]
                             if path == CI else text), (
            f"{path.name} carries a commit hash; accepted commits belong in "
            "AUDIT_ACCEPTED_COMMITS, outside the tree")


def test_the_ci_message_check_and_the_audit_use_the_scanner():
    ci = CI.read_text(encoding="utf-8")
    assert "scripts/scan_published_text.py --git-range" in ci, (
        "the CI commit-message check no longer runs the shared scanner; a "
        "literal grep there cannot see the hashed private names")
    audit = AUDIT.read_text(encoding="utf-8")
    assert "scripts/scan_published_text.py" in audit
    assert "--all-commits" in audit, "the audit no longer scans history"
