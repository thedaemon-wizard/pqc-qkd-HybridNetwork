"""One fact, one place.

A paragraph copied into two documents is two things that can drift apart, and
the drift is silent: both copies read as authoritative, and a reader who finds
the stale one has no way to know the other exists.

This found exactly one instance when written -- a "Superseded" note duplicated
word for word between `ARCHITECTURE.md` and `docs/IMAGE2_MULTIHOP.md`. That is
the useful signal-to-noise ratio for a guard like this: it is not flagging
boilerplate, it is flagging the real thing.

Deliberately narrow so it stays that way:
  * paragraphs under 140 characters are ignored -- short repeated phrases
    ("see the table below") are normal prose, not duplicated content
  * fenced code blocks are stripped before comparison; the same snippet quoted
    in two places is usually correct, since it is quoting a third thing
  * headings are excluded
"""
from __future__ import annotations

import collections
import pathlib
import re
import subprocess

REPO = pathlib.Path(__file__).resolve().parents[1]
MIN_CHARS = 140


def _tracked_md() -> list[str]:
    out = subprocess.run(["git", "ls-files"], cwd=REPO,
                         capture_output=True, text=True).stdout.split()
    return [f for f in out if f.endswith(".md") and not f.startswith("submodules/")]


def _paragraphs(rel: str) -> list[str]:
    txt = (REPO / rel).read_text(encoding="utf-8")
    txt = re.sub(r"```.*?```", "", txt, flags=re.S)
    out = []
    for para in re.split(r"\n\s*\n", txt):
        norm = " ".join(para.split()).replace("|", "")
        if len(norm) >= MIN_CHARS and not norm.startswith("#"):
            out.append(norm)
    return out


def test_no_long_paragraph_appears_in_two_documents():
    index: dict[str, set[str]] = collections.defaultdict(set)
    for f in _tracked_md():
        for para in _paragraphs(f):
            index[para].add(f)
    dupes = {p: sorted(fs) for p, fs in index.items() if len(fs) > 1}
    assert dupes == {}, (
        "these paragraphs are written out in more than one document, so they "
        "are two things that can drift apart:\n  "
        + "\n  ".join(f"{fs}: {p[:100]}..." for p, fs in dupes.items()))


def test_the_guard_can_see_something():
    """Not vacuous: it must be reading real paragraphs."""
    total = sum(len(_paragraphs(f)) for f in _tracked_md())
    assert total > 100, (
        f"only {total} paragraphs met the length threshold -- either the "
        f"documents shrank a lot or the parser broke")
