"""WireGuard's message rekey limit is $`2^{60}`$, not 260.

QCI-CAT deliverable D6.1 states that WireGuard rekeys "after 120 seconds or
after $`2^{60}`$ messages". The exponent is typeset as a superscript, and
plain-text extraction of the PDF flattens it into the adjacent digit, giving
"260 messages". That flattened form was quoted in two places and attributed to
D6.1, understating the limit by about eighteen orders of magnitude while
naming a primary source for it.

Nothing in the source is wrong, so the fix is to quote it as printed. This
guard keeps the extraction artefact from coming back through a fresh
copy-and-paste out of the same PDF.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# The artefact, not the number: "260" alone is an ordinary value elsewhere.
ARTEFACT = re.compile(r"\b260\s+messages\b", re.I)
SELF = f"tests/{Path(__file__).name}"


def _tracked() -> list[str]:
    out = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT,
                         capture_output=True, text=True, check=False).stdout
    return [p for p in out.split("\0") if p]


def test_there_is_a_tree_to_scan():
    assert len(_tracked()) > 100


def test_no_tracked_file_quotes_the_flattened_exponent():
    offenders = []
    for rel in _tracked():
        if rel == SELF:
            continue
        p = ROOT / rel
        if not p.is_file():
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for n, line in enumerate(text.splitlines(), 1):
            if ARTEFACT.search(line):
                offenders.append(f"{rel}:{n}")
    assert not offenders, (
        f"'260 messages' is a PDF-extraction artefact of 2^60: {offenders}. "
        "Quote D6.1 as printed.")


def test_the_pattern_matches_the_artefact_and_not_the_correction():
    assert ARTEFACT.search("after 120 seconds or after 260 messages")
    assert not ARTEFACT.search("after 120 seconds or after 2^60 messages")
    assert not ARTEFACT.search("after $`2^{60}`$ messages")
