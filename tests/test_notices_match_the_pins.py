"""A version claimed in THIRD_PARTY_NOTICES.md must match the pinned submodule.

This exists because the notices table said openQKDsecurity was pinned "3
commits **ahead** of tag v2.2.0, so it already includes that release". The pin
was 3 commits BEHIND. `git describe` read `v2.1.0-2-g6ffeed8` and v2.2.0 was
not an ancestor of HEAD; the comparison had simply been written the wrong way
round.

Nothing could have caught it. Checklist row 6.6 -- "docs/THIRD_PARTY_NOTICES.md
matches the pinned versions" -- is prose with no command attached, and no test
or CI job compared the table against `git submodule status`. A licence and
provenance file that asserts currency the repository does not have is the same
defect class as a page reporting a cross-check it never ran.

The check is deliberately narrow. It does not try to parse every claim in the
table; it extracts bolded `vX.Y.Z` version claims per submodule row and
requires the pinned commit to actually BE that tag. Anything subtler -- "active",
push dates, licence names -- stays human-checked, because a test that pretends
to verify prose is worse than one that admits its scope.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
NOTICES = ROOT / "docs" / "THIRD_PARTY_NOTICES.md"

# `| `name` | licence | ... | **vX.Y.Z** ... |` -- only rows making a version claim.
ROW = re.compile(r"^\|\s*`([A-Za-z0-9_.-]+)`\s*\|.*$", re.M)
VERSION = re.compile(r"\*\*(v\d+\.\d+(?:\.\d+)?)\*\*")


def _submodule_paths() -> dict[str, str]:
    """Map submodule basename -> path, from .gitmodules."""
    out = subprocess.run(
        ["git", "config", "-f", ".gitmodules", "--get-regexp", r"submodule\..*\.path"],
        cwd=ROOT, capture_output=True, text=True, check=False,
    ).stdout
    paths = {}
    for line in out.splitlines():
        _, _, path = line.partition(" ")
        if path:
            paths[Path(path).name] = path
    return paths


def _claimed_versions() -> dict[str, str]:
    """Submodule name -> version string the notices table claims for it."""
    claims = {}
    paths = _submodule_paths()
    for line in NOTICES.read_text(encoding="utf-8").splitlines():
        m = ROW.match(line)
        if not m:
            continue
        name = m.group(1)
        if name not in paths:
            continue
        v = VERSION.search(line)
        if v:
            claims[name] = v.group(1)
    return claims


def test_the_table_still_makes_version_claims():
    """Guard the guard: if the claims vanish, this file is silently vacuous."""
    claims = _claimed_versions()
    assert claims, (
        "no bolded vX.Y.Z version claims found for any submodule row in "
        f"{NOTICES.relative_to(ROOT)} -- either the format changed or the "
        "claims were removed, and this test is no longer checking anything."
    )


@pytest.mark.parametrize("name,claimed", sorted(_claimed_versions().items()))
def test_claimed_version_is_the_pinned_commit(name, claimed):
    path = _submodule_paths()[name]
    sub = ROOT / path
    if not (sub / ".git").exists():
        pytest.skip(f"{path} not checked out")

    # Does the pinned commit actually carry that tag?
    tag_sha = subprocess.run(
        ["git", "rev-list", "-n", "1", claimed],
        cwd=sub, capture_output=True, text=True, check=False,
    ).stdout.strip()
    head_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=sub, capture_output=True, text=True, check=False,
    ).stdout.strip()

    if not tag_sha:
        # Skipping here was itself a hole: the first negative test of this file
        # claimed "v2.9.9" and the run went GREEN, because an invented version
        # is exactly a tag that cannot be resolved. Only skip when the clone
        # genuinely has no tags at all; otherwise an unresolvable claim is the
        # error, not a reason to look away.
        has_any_tag = subprocess.run(
            ["git", "tag"], cwd=sub, capture_output=True, text=True, check=False,
        ).stdout.strip()
        if not has_any_tag:
            pytest.skip(f"{name} has no tags locally (shallow clone)")
        raise AssertionError(
            f"{name}: THIRD_PARTY_NOTICES.md claims {claimed}, but no such tag "
            f"exists in {path}. The clone does have tags, so this is a wrong or "
            "invented version rather than a shallow checkout."
        )

    describe = subprocess.run(
        ["git", "describe", "--tags", "HEAD"],
        cwd=sub, capture_output=True, text=True, check=False,
    ).stdout.strip()

    assert tag_sha == head_sha, (
        f"{name}: THIRD_PARTY_NOTICES.md claims {claimed}, but the pinned commit "
        f"is {head_sha[:8]} ({describe or 'no describe'}), and {claimed} is "
        f"{tag_sha[:8]}.\n"
        "Check the DIRECTION before editing the table: `git rev-list --count "
        "HEAD..<tag>` is how far BEHIND the pin is, and `<tag>..HEAD` is how far "
        "ahead. Reading one as the other is what put a false 'already includes "
        "that release' claim in this file."
    )
