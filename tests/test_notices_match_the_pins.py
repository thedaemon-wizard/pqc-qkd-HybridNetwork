"""A version claimed in THIRD_PARTY_NOTICES.md must match the pinned submodule.

This exists because the notices table said openQKDsecurity was pinned "3
commits **ahead** of tag v2.2.0, so it already includes that release". The pin
was 3 commits BEHIND -- `git rev-list --count A..B` had been read backwards.

THEN THIS TEST WAS AUDITED AND HAD THE SAME HOLE IT EXISTED TO CLOSE, twice
over.

Hole 1 -- it only saw rows whose version was **bolded**. Of the 15 submodule
rows, 3 carried a bolded `vX.Y.Z` and were checked; 12 were silently skipped.
Every row later found to be wrong was in the skipped 12. The SeQUeNCe row read
`v0.8.5, 2026-05-12 (active)` with no bold, so it was invisible -- and it was
false twice: the pin is v0.8.5 PLUS TEN COMMITS, and upstream had shipped
v1.0.0, leaving the pin 276 commits behind. `liboqs` was bolded as **0.16.0**
with no `v` and was also unmatched (it happened to be correct).

Hole 2 -- it resolved tags in the LOCAL clone and skipped when none were found.
Twelve of fifteen submodules are shallow here with zero tags, so even a matched
claim would have skipped. Two independent reasons for the same row to pass
without being examined.

The guard-the-guard assertion did not help: it required only that SOME claim
exist anywhere in the table, so 3 of 15 looked healthy.

What changed:

  * every submodule row must carry a version claim, bolded or not, and a row
    without one FAILS rather than being passed over;
  * versions resolve through `git ls-remote --tags` against the submodule's own
    URL, so checkout depth is irrelevant;
  * the pinned commit comes from `git ls-tree HEAD`, the index, so it is right
    even when the submodule is not checked out at all.

Only a genuine absence of network skips now, and it skips loudly.
"""
from __future__ import annotations

import re
import subprocess
from functools import lru_cache
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
NOTICES = ROOT / "docs" / "THIRD_PARTY_NOTICES.md"

ROW = re.compile(r"^\|\s*`([A-Za-z0-9_.-]+)`\s*\|.*$", re.M)

# The Activity column is the last cell. Scoping to it matters: a first attempt
# scanned the whole row and read "GPL-3.0" out of the LICENCE column as version
# "3.0", failing wgephemeralpeer for a defect that did not exist. A guard that
# fires on correct documentation is worse than no guard.
ACTIVITY_CELL = -1

# A pinned SHA, in backticks. This is the primary claim because it is
# unambiguous, checkable without network, and works for rows that pin an
# untagged commit -- which several legitimately do.
PINNED_SHA = re.compile(r"`([0-9a-f]{7,40})`")

# A bolded tag ATTACHED TO THE WORD "pinned" is the stronger claim: not merely
# "this is the pin" but "the pin is this release".
#
# Both halves are load-bearing. Bold separates an asserted tag from prose like
# "post-v1.0.1", a lineage statement this test should not adjudicate. Proximity
# to "pinned" separates a claim about THIS submodule from a bolded version that
# belongs to another project -- the oqs-provider row discusses the liboqs
# pairing and bolds **0.15.0** and **0.16.0**, neither of which is oqs-provider's
# pin. A first version of this rule matched any bolded version in the cell and
# failed that row for a defect that did not exist.
# IGNORECASE because the liboqs row begins its claim with a capital -- "Pinned
# to tag **0.16.0**" -- and a case-sensitive version of this pattern silently
# skipped that row, reintroducing in one line the exact hole this rewrite
# exists to close.
BOLD_TAG = re.compile(
    r"pinned(?:\s+\S+){0,5}?\s*\*\*v?(\d+\.\d+(?:\.\d+)?)\*\*", re.IGNORECASE
)


def _run(args: list[str], cwd: Path = ROOT) -> str:
    return subprocess.run(
        args, cwd=cwd, capture_output=True, text=True, check=False
    ).stdout


@lru_cache(maxsize=1)
def _submodules() -> dict[str, tuple[str, str]]:
    """basename -> (path, url), from .gitmodules."""
    out = _run(["git", "config", "-f", ".gitmodules", "--get-regexp",
                r"submodule\..*\.path"])
    subs = {}
    for line in out.splitlines():
        key, _, path = line.partition(" ")
        if not path:
            continue
        url = _run(["git", "config", "-f", ".gitmodules", "--get",
                    key.replace(".path", ".url")]).strip()
        subs[Path(path).name] = (path, url)
    return subs


@lru_cache(maxsize=1)
def _claims() -> dict[str, dict[str, str | None]]:
    """Submodule name -> {sha, tag} as claimed by its Activity cell."""
    subs = _submodules()
    found: dict[str, dict[str, str | None]] = {}
    for line in NOTICES.read_text(encoding="utf-8").splitlines():
        m = ROW.match(line)
        if not m or m.group(1) not in subs:
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        activity = cells[ACTIVITY_CELL] if len(cells) >= 2 else ""
        sha = PINNED_SHA.search(activity)
        tag = BOLD_TAG.search(activity)
        found[m.group(1)] = {
            "sha": sha.group(1) if sha else None,
            "tag": tag.group(1) if tag else None,
        }
    return found


@lru_cache(maxsize=1)
def _pins() -> dict[str, str]:
    """Submodule path -> pinned SHA, read from the INDEX.

    `git submodule status` reports the working tree, which is empty for the
    twelve submodules that are not checked out here. The index always knows.

    `git ls-files -s`, not `git ls-tree HEAD`. This read the committed tree
    until 2026-08-27, which made it lag one commit behind whatever is being
    prepared: the arnika bump to `9d44332` staged the new gitlink AND the new
    notices row together, and the guard failed with "the row says `9d44332`,
    but the index pins 018b3541" -- naming the index in its own error message
    while not reading it. It would then have passed on the commit it had just
    rejected. A guard that only evaluates the previous commit cannot gate the
    next one; the same shape as running a new check before `git add`.
    """
    pins = {}
    for line in _run(["git", "ls-files", "-s", "submodules/"]).splitlines():
        meta, _, path = line.partition("\t")
        parts = meta.split()
        # 160000 is git's gitlink mode -- a submodule rather than a blob.
        if len(parts) >= 2 and parts[0] == "160000":
            pins[Path(path).name] = parts[1]
    return pins


@lru_cache(maxsize=32)
def _remote_tags(url: str) -> dict[str, str] | None:
    """tag -> commit SHA, straight from the remote. None if unreachable."""
    proc = subprocess.run(
        ["git", "ls-remote", "--tags", url],
        capture_output=True, text=True, check=False, timeout=120,
    )
    if proc.returncode != 0:
        return None
    tags: dict[str, str] = {}
    for line in proc.stdout.splitlines():
        sha, _, ref = line.partition("\t")
        name = ref.removeprefix("refs/tags/")
        # An annotated tag lists the tag object and then `name^{}` for the
        # commit it points at. The peeled entry is the one to compare against a
        # submodule pin, and it arrives second, so this overwrite is deliberate.
        tags[name.removesuffix("^{}")] = sha.strip()
    return tags


def test_the_table_is_read_for_every_submodule():
    """Guard the guard, counted rather than existential.

    The previous version asserted only that SOME claim existed anywhere in the
    table, which is why 3-of-15 coverage read as healthy for as long as it did.
    """
    assert set(_claims()) == set(_submodules()), (
        f"parsed {len(_claims())} rows for {len(_submodules())} submodules; "
        f"missing: {sorted(set(_submodules()) - set(_claims()))}. A row's "
        "format changed and it is no longer being read."
    )


@pytest.mark.parametrize("name", sorted(_submodules()))
def test_the_row_states_the_pinned_commit(name):
    """Every row must name the SHA it is pinned to, and name it correctly.

    Cheap, offline, unambiguous, and true for tagged and untagged pins alike --
    which is why it is the primary check rather than the version claim. The
    SeQUeNCe row named a release and no SHA, and was wrong about the release.
    """
    claim = _claims()[name]
    pinned = _pins().get(name)
    assert pinned, f"{name}: no gitlink for {_submodules()[name][0]} in the index"

    assert claim["sha"], (
        f"{name}: the Activity cell names no pinned commit, so the row asserts "
        f"nothing checkable. Add the short SHA in backticks -- it is {pinned[:8]}."
    )
    assert pinned.startswith(claim["sha"]), (
        f"{name}: the row says the pin is `{claim['sha']}`, but the index "
        f"pins {pinned[:12]}."
    )


@pytest.mark.parametrize("name", sorted(_submodules()))
def test_a_bolded_tag_really_is_the_pin(name):
    """A bolded version is an equality claim, so hold it to one.

    Bold is what separates "the pin IS this release" from prose about lineage
    such as "post-v1.0.1", which is a human judgement this test should not
    pretend to adjudicate.
    """
    claimed = _claims()[name]["tag"]
    if claimed is None:
        pytest.skip(f"{name}: row makes no bolded tag claim")

    _, url = _submodules()[name]
    pinned = _pins()[name]
    tags = _remote_tags(url)
    if tags is None:
        pytest.skip(f"{name}: cannot reach {url} to resolve tags (offline?)")

    candidates = [c for c in (f"v{claimed}", claimed) if c in tags]
    assert candidates, (
        f"{name}: the row bolds {claimed}, but {url} has no such tag. "
        f"Nearest: {sorted(tags)[-5:]}"
    )
    tag_sha = tags[candidates[0]]
    assert tag_sha == pinned, (
        f"{name}: the row bolds {claimed} ({tag_sha[:8]}), but the pin is "
        f"{pinned[:8]}.\n"
        "Check the DIRECTION before editing: `git rev-list --count HEAD..<tag>` "
        "is how far BEHIND the pin is, `<tag>..HEAD` how far ahead. Reading one "
        "as the other is what put a false 'already includes that release' claim "
        "in this file. If the pin is deliberately untagged, drop the bold and "
        "say so."
    )
