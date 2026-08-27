"""Publication constraints, as executable checks rather than recurring manual sweeps.

Four properties of this repository have to hold before it is published, and all
four had been verified by hand more than once. A property checked by hand is a
property that gets re-checked by hand forever, and the answer is only as good as
the last person's grep. These are the same checks, written down.

  1. No Japanese text in a tracked file -- with two deliberate exceptions.
  2. No emoji in documentation files (research and industry material).
  3. No AI-tooling attribution anywhere in tracked content.
  4. No host names, addresses or credentials for the public demo.

The Japanese exception is the interesting one, and it is why this is a test
rather than a `grep | wc -l` in a checklist row. `VERIFICATION_CHECKLIST.md`
row 4.2.2 documents the browser check for Japanese text, and to do that it
quotes the Unicode ranges:

    document.documentElement.innerText.match(/[<hiragana-katakana>...]/g)

The row cannot state the check without containing the characters it looks for.
A naive "zero Japanese characters" rule fails on it, and the obvious fix --
deleting the row -- removes the check. So the rule is "exactly one, and it is
that line", which is precise and stays honest if the row ever moves.

This file is the second exception, for the same reason: it defines the regex.
It found that out the hard way -- the first CI run failed on line 41, its own
`JAPANESE` pattern, while the local run had been green because `git ls-files`
did not yet list an uncommitted file. Worth remembering when writing any guard
that scans tracked content: verify it AFTER `git add`, or the subject is
invisible to it.

Formula rendering is deliberately NOT checked here: it needs GitHub's own
Markdown renderer and lives in `services/webui-frontend/src/lib/docsLatex.test.ts`,
where the KaTeX dependency already is.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

BINARY = re.compile(r"\.(pdf|png|jpg|jpeg|gif|webm|mp4|ico|woff2?|zip|whl|so)$", re.I)

JAPANESE = re.compile(r"[぀-ヿ一-鿿]")
EMOJI = re.compile(r"[\U0001F300-\U0001FAFF✀-➿⬀-⯿]")
# `claude` is on this list because it is the name that actually gets written:
# the default attribution is "Generated with Claude Code", which contains no
# vendor word at all, so a list of vendors alone cannot fail on it. The CI
# commit-message job has always grepped for it; this pattern had not, and this
# is the only check that reads file CONTENT rather than commit messages.
# Naming it makes this file match its own pattern -- which is what SELF below
# is for. The exemption is one named file, not a blanket skip.
TOOLING = re.compile(r"\b(anthropic|claude|copilot|chatgpt|openai)\b", re.I)

# Files that must contain a forbidden pattern in order to detect it. There are
# exactly two kinds and both are unavoidable: the checklist row that documents
# the browser check FOR Japanese (it cannot state the check without quoting the
# ranges), and this file, which defines the matching regexes.
#
# This test failed on itself the first time it ran in CI, and passed locally --
# because `git ls-files` did not yet list the file. A green local run on an
# uncommitted guard proves nothing about the guard.
SELF = f"tests/{Path(__file__).name}"
JAPANESE_EXEMPTION = ("VERIFICATION_CHECKLIST.md", "4.2.2")


def _tracked() -> list[str]:
    out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=False)
    return [f for f in out.stdout.split() if not BINARY.search(f)]


def _lines(rel: str) -> list[tuple[int, str]]:
    p = ROOT / rel
    if not p.is_file():
        return []
    try:
        return list(enumerate(p.read_text(encoding="utf-8", errors="ignore").splitlines(), 1))
    except OSError:
        return []


TRACKED = _tracked()


def test_there_are_tracked_files_to_scan():
    """Guard the guard: an empty file list would make every check below pass."""
    assert len(TRACKED) > 100, f"only {len(TRACKED)} tracked text files found"


def test_the_only_japanese_is_the_row_that_documents_the_japanese_check():
    offenders = [
        (f, n, line.strip()[:80])
        for f in TRACKED
        if f != SELF
        for n, line in _lines(f)
        if JAPANESE.search(line)
    ]
    # Exactly one, and it must be the row we expect -- not merely "one somewhere".
    assert len(offenders) == 1, (
        "expected exactly one Japanese-bearing line (the checklist row that "
        f"quotes the detection ranges), found {len(offenders)}: "
        f"{[(f, n) for f, n, _ in offenders]}"
    )
    f, _, text = offenders[0]
    exempt_file, exempt_row = JAPANESE_EXEMPTION
    assert f == exempt_file and exempt_row in text, (
        f"the one Japanese-bearing line moved: it is now {f} -- {text!r}. If row "
        f"{exempt_row} was renumbered, update JAPANESE_EXEMPTION; if this is new "
        "prose, translate it."
    )


@pytest.mark.parametrize("doc", sorted(f for f in _tracked() if f.endswith(".md")))
def test_documentation_carries_no_emoji(doc):
    """Research and industry material. The UI is exempt; these are documents."""
    found = {m.group() for _, line in _lines(doc) for m in EMOJI.finditer(line)}
    assert not found, f"{doc} contains emoji: {sorted(found)}"


def test_no_ai_tooling_attribution_in_tracked_content():
    """The scan pattern itself is the only legitimate mention."""
    offenders = []
    for f in TRACKED:
        for n, line in _lines(f):
            if not TOOLING.search(line):
                continue
            # A scanner must name what it forbids. Exactly four files may:
            # the CI job, the two audit scripts, and the checklist row that
            # documents them -- plus this test, via SELF.
            if f in (".github/workflows/ci.yml", "VERIFICATION_CHECKLIST.md",
                     "scripts/secret_scan.sh", "scripts/audit_github_surface.sh",
                     SELF):
                continue
            offenders.append((f, n, line.strip()[:80]))
    assert not offenders, f"AI-tooling references in tracked content: {offenders}"


def test_no_demo_host_identifiers_in_tracked_files():
    """A hostname or address for the public demo must not be committed."""
    host = re.compile(r"\b\d{1,3}(\.\d{1,3}){3}\b")
    private = re.compile(r"^(10\.|127\.|172\.(1[6-9]|2\d|3[01])\.|192\.168\.|0\.|255\.)")
    offenders = []
    for f in TRACKED:
        for n, line in _lines(f):
            for m in host.finditer(line):
                ip = m.group()
                # Documentation and compose legitimately carry RFC 1918 and
                # loopback addresses for the local lab topology.
                if private.match(ip) or ip.startswith("0.0.0.0"):
                    continue
                offenders.append((f, n, ip))
    assert not offenders, (
        f"non-private IP addresses in tracked files: {offenders}. The public "
        "demo's address must not be committed."
    )


def test_the_tooling_pattern_matches_what_the_tools_actually_emit():
    """Positive control: a blocklist is only as good as the names on it.

    The scan above can only fail on a string `TOOLING` matches, so a missing
    name is a silent hole -- every tracked file passes and the guard looks
    green. `claude` was that hole: the four vendor words were all present
    while the one product name the tooling signs with was not.

    These literals can live in this file and nowhere else. It is the only
    file exempt from the scan via SELF, so moving the control into a fixture
    or a data file would make it trip the very guard it is testing.
    """
    for sample in (
        "Generated with Claude Code",
        "Co-Authored-By: Claude <noreply@example.invalid>",
        "assisted by Copilot",
        "drafted with ChatGPT",
        "an Anthropic model",
    ):
        assert TOOLING.search(sample), f"TOOLING does not match {sample!r}"
    # And it stays word-bounded, so ordinary prose is not collateral.
    for benign in ("claudette", "openairport"):
        assert not TOOLING.search(benign), f"TOOLING over-matches {benign!r}"
