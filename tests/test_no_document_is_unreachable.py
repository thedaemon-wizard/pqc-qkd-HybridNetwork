"""Every tracked document must be reachable by following links.

`docs/IMAGE2_MULTIHOP.md` was written, committed and then reachable only by
knowing its filename: `IMAGE1_VPN_SCOPE.md` is linked from `ARCHITECTURE.md`
and `docs/phases.md`, and its companion was linked from nowhere.

That is a quieter failure than a broken link. A dead link announces itself the
moment someone clicks it; an unreferenced file simply never gets read, so it
drifts out of step with the code and nobody notices -- and the effort that went
into writing it is wasted.

`tests/test_referenced_paths_exist.py` checks the other direction (a link
resolves to a file). This checks that a file is arrived at.
"""
from __future__ import annotations

import pathlib
import re
import subprocess

REPO = pathlib.Path(__file__).resolve().parents[1]
LINK = re.compile(r"\]\(([^)#\s]+\.md)")

#: Reachable by browsing the directory they document, not by a prose link.
#: Component READMEs are the convention, not an oversight.
COMPONENT_READMES = {"services/arnika-vici/README.md", "deploy/README.md"}

#: The entry point. Nothing links to it; everything links from it.
ROOT = {"README.md"}


def _tracked_md() -> list[str]:
    out = subprocess.run(["git", "ls-files"], cwd=REPO,
                         capture_output=True, text=True).stdout.split()
    return [f for f in out if f.endswith(".md") and not f.startswith("submodules/")]


def _linked_targets(files: list[str]) -> set[str]:
    linked: set[str] = set()
    for f in files:
        base = (REPO / f).parent
        for target in LINK.findall((REPO / f).read_text(encoding="utf-8")):
            if target.startswith("http"):
                continue
            try:
                linked.add(str((base / target).resolve().relative_to(REPO)))
            except ValueError:
                pass
    return linked


def test_every_document_is_linked_from_another():
    files = _tracked_md()
    linked = _linked_targets(files)
    orphans = sorted(set(files) - linked - ROOT - COMPONENT_READMES)
    assert orphans == [], (
        "these are tracked but nothing links to them, so they will be read "
        f"only by someone who already knows the filename: {orphans}")


def test_the_exemptions_still_exist():
    """An exemption list that names a deleted file hides a real orphan."""
    files = set(_tracked_md())
    stale = sorted((ROOT | COMPONENT_READMES) - files)
    assert stale == [], f"exempted but no longer tracked: {stale}"


def test_the_check_is_not_vacuous():
    """It must be capable of finding something."""
    files = _tracked_md()
    assert len(files) > 10, "too few documents for this to mean anything"
    assert _linked_targets(files), "no links parsed at all -- the regex broke"
