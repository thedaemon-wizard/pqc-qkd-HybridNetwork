"""Operator-private files must be protected by a rule that travels.

The operator keeps working files out of this repository -- planning notes, host
access details, commercial material. They were held back by `.git/info/exclude`,
which is **per-clone**: it is not committed and does not travel. Verified by
simulating a clean clone with only the repository's own `.gitignore`, where
`git add -A` staged both of them.

It had held in the working copy, which is why several `git add -A` runs never
staged them, but that was a property of one machine rather than of the project.

The safe harbour is a generic `/private/` directory. Generic on purpose: listing
the filenames in `.gitignore` would disclose them in a public repository, which
is exactly what the rule exists to prevent. `VERIFICATION_CHECKLIST.md` row 6.4
made that mistake -- it spelled out two private filenames while asserting that
"a reference from a tracked file discloses the name", and its own grep returned
the checklist.

This test asserts the mechanism exists and works. It cannot assert the operator
has moved anything into it, because doing so would require knowing the names.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GITIGNORE = ROOT / ".gitignore"


def _ignored(relpath: str) -> bool:
    """Ask git itself, rather than re-implementing gitignore matching."""
    return subprocess.run(
        ["git", "check-ignore", "-q", relpath],
        cwd=ROOT, capture_output=True, check=False,
    ).returncode == 0


def test_the_private_directory_is_ignored():
    assert _ignored("private/anything.md"), (
        "/private/ is no longer ignored, so operator-private files placed there "
        "would be committed."
    )
    assert _ignored("private/nested/deep/file.txt"), "the rule must cover subdirectories"


def test_the_rule_lives_in_gitignore_not_only_in_a_local_exclude():
    """The whole point: a per-clone exclude does not protect a fresh clone."""
    assert "/private/" in GITIGNORE.read_text(encoding="utf-8"), (
        "the /private/ rule is not in the tracked .gitignore. If it has moved to "
        ".git/info/exclude, the protection has stopped travelling to other clones "
        "-- which is the defect this replaced."
    )


def test_gitignore_does_not_name_the_private_files():
    """A rule that names what it hides defeats itself in a public repository."""
    text = GITIGNORE.read_text(encoding="utf-8").lower()
    for token in ("monetization", "monetisation", "ssh_info"):
        assert token not in text, (
            f".gitignore contains {token!r}. Naming a private file in a tracked "
            "file discloses it; that is why the rule is a generic directory."
        )


def test_no_tracked_file_names_the_private_files():
    """Same rule, applied to the whole repository rather than one file."""
    tracked = subprocess.run(
        ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=False
    ).stdout.split()
    offenders = []
    for rel in tracked:
        p = ROOT / rel
        if not p.is_file():
            continue
        try:
            body = p.read_text(encoding="utf-8", errors="ignore").lower()
        except OSError:
            continue
        # This test file necessarily contains the tokens in prose, as does any
        # future test of the same rule; exempt only by path, never by content.
        if rel == f"tests/{Path(__file__).name}":
            continue
        if "monetization.md" in body or "ssh_info_" in body:
            offenders.append(rel)
    assert not offenders, (
        f"these tracked files name an operator-private file: {offenders}. "
        "Describe the rule, not the filenames."
    )
