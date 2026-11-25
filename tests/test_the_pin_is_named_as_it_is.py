"""Every sentence that names the arnika pin names the current one.

Re-pinning arnika on 2026-11-21 (f4cf9ba -> 0bb8401, PR #157) updated the
repository's statements of the pin, except three comments that went on calling
f4cf9ba "the pin" -- "the head of the open, unmerged upstream PR #51" -- after
#51 had merged: the headers of docker-compose.yml and
docker-compose.strongswan.yml, and section 7 of docs/threat-model.md. They were
found by reading, on 2026-11-25. Nothing had failed, because they are prose.

This reads the forms the repository uses to state the pin in the present tense
-- "pinned to <sha>", "the (arnika) pin is <sha>", "the (arnika) pin, <sha>",
"at the pin, <sha>" -- in every tracked text file, and fails on either of:

  * one of them naming a commit that was arnika's pin before, or #51's merge
    commit (never the pin, and the likeliest wrong guess);
  * one of them, on a line that mentions arnika, naming a commit that is not
    the pin in the index.

Sentences about an earlier pin use other words ("the pin before it was",
"at f4cf9ba", "the previous pin, f4cf9ba"), so they pass. The dated records
are not read: CHANGELOG.md and docs/measurements/.

When the pin moves again, add the old one to PREVIOUS.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

PREVIOUS = {
    "3a8cc13": "the pin of release 0.1.0",
    "f4cf9ba": "the pin from release 0.2.0 to 2026-11-21: #51's head as of 2026-09-24",
    "e37d043": "#51's last head (2026-11-05): measured on the development machine, never the pin",
    "c850db6": "#51's merge commit (2026-11-20): never the pin",
}

STATEMENT = re.compile(
    r"\b(?:pinned to|[Tt]he (?:arnika )?pin(?: is|,)|at the pin,)\s*`?([0-9a-f]{7,40})\b")

NOT_READ = ("CHANGELOG.md", "docs/measurements/", "submodules/",
            "tests/test_the_pin_is_named_as_it_is.py")


def _pin() -> str:
    out = subprocess.run(["git", "ls-files", "-s", "submodules/arnika"], cwd=REPO,
                         capture_output=True, text=True, check=True).stdout.split()
    assert out and out[0] == "160000", f"submodules/arnika is not a gitlink in the index: {out}"
    return out[1]


def _text_files():
    listing = subprocess.run(["git", "ls-files", "-s", "-z"], cwd=REPO,
                             capture_output=True, text=True, check=True).stdout
    for entry in filter(None, listing.split("\0")):
        mode, _, rest = entry.partition(" ")
        path = rest.split("\t", 1)[1]
        if mode == "160000" or path.startswith(NOT_READ):
            continue
        p = REPO / path
        if not p.is_file() or p.stat().st_size > 2_000_000:
            continue
        try:
            yield path, p.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue


def _statements():
    for path, text in _text_files():
        for n, line in enumerate(text.splitlines(), 1):
            for m in STATEMENT.finditer(line):
                yield path, n, line, m.group(1)


def test_no_sentence_calls_an_earlier_commit_the_pin():
    wrong = []
    for path, n, line, sha in _statements():
        for old, what in PREVIOUS.items():
            if sha.startswith(old) or old.startswith(sha):
                wrong.append(f"{path}:{n}: names {sha} ({what}) as the pin\n    {line.strip()[:160]}")
    assert not wrong, "\n".join(wrong)


def _about_arnika(line: str) -> bool:
    """A table row is about its first cell; any other line, about what it names."""
    s = line.strip()
    if s.startswith("|"):
        return "arnika" in s.split("|")[1].lower()
    return "arnika" in s.lower()


def test_a_sentence_about_arnika_names_the_pin_in_the_index():
    pin = _pin()
    wrong = [f"{path}:{n}: names {sha}, the pin is {pin[:7]}\n    {line.strip()[:160]}"
             for path, n, line, sha in _statements()
             if _about_arnika(line) and not pin.startswith(sha)]
    assert not wrong, "\n".join(wrong)


def test_the_forms_are_actually_found():
    """Guard the guard: the statements that are right must be seen, or both tests pass on nothing."""
    pin = _pin()
    found = {(path, sha) for path, _, _, sha in _statements() if pin.startswith(sha)}
    paths = {path for path, _ in found}
    for expected in (".gitmodules", "README.md", "docs/THIRD_PARTY_NOTICES.md", "nodes/alice/Dockerfile"):
        assert expected in paths, f"no statement of the pin found in {expected}; the pattern no longer matches"


def test_the_pattern_tells_a_statement_from_history():
    current = "pinned to `0bb8401`, upstream main"
    assert [m.group(1) for m in STATEMENT.finditer(current)] == ["0bb8401"]
    assert [m.group(1) for m in STATEMENT.finditer("The arnika pin, f4cf9ba, is the head")] == ["f4cf9ba"]
    assert [m.group(1) for m in STATEMENT.finditer("The pin is 0bb8401, arnika's main")] == ["0bb8401"]
    for history in ("The pin before it was `f4cf9ba`, #51's head",
                    "Since the previous pin, `f4cf9ba` of 2026-09-24",
                    "at `f4cf9ba`, the pin until 2026-11-21",
                    "The pin moved to `f4cf9ba`, the head of arnika PR #51"):
        assert not list(STATEMENT.finditer(history)), history
