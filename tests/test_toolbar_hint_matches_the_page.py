"""The "Press Run first" hint must only appear on pages that have a Run button.

`ExportToolbar` ended both animation tooltips with "Press Run first."
unconditionally. Nine pages mount that toolbar and only two -- `/e2e` and
`/paper-flow` -- have a Run control, so on the other seven the hint instructed
the reader to press something that does not exist. `/bb84` in particular
animates continuously and has no start button at all; its WebM tooltip still
said to press Run.

Nothing caught it because the string is correct in the component that owns it
and only wrong in combination with the page that mounts it. That is the same
shape as the two view/model splits already recorded in this repository -- the
`/e2e` banner recomputing failure fatality, and the `/pqc` heading hardcoding
"FIPS 204" over FIPS 205 sizes. In each case one file was right on its own.

So the check has to be cross-file: whichever pages have a Run button are
exactly the pages that may opt in.

Deliberately a source check rather than a browser check. The browser can only
show what one page does at a time, and the defect is a disagreement between a
set of pages and a shared component.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PAGES = ROOT / "services" / "webui-frontend" / "src" / "pages"
TOOLBAR = ROOT / "services" / "webui-frontend" / "src" / "components" / "ExportToolbar.tsx"

# The visible label of a start control, as rendered. Matches `▶ Run` but not
# `▶ Resume`, which is a different control and does not imply a fresh start.
RUN_BUTTON = re.compile(r"▶\s*Run\b")
OPT_IN = re.compile(r"\bhasRunControl\b")
MOUNTS_TOOLBAR = re.compile(r"<ExportToolbar\b")


def _pages() -> list[Path]:
    return sorted(PAGES.glob("*.tsx"))


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def test_the_hint_is_conditional_at_all():
    """Guard the guard: if the string goes back to being unconditional, the
    per-page assertions below would all still pass while every tooltip lied."""
    src = _read(TOOLBAR)
    assert "Press Run first." in src, "the hint vanished; this test is now vacuous"
    assert re.search(r"hasRunControl\s*\?", src), (
        "ExportToolbar no longer chooses the run hint conditionally, so every "
        "page that mounts it claims a Run button again."
    )
    # And it must not be spelled inline in the tooltips any more.
    for line in src.splitlines():
        if "title={`" in line and "Press Run first." in line:
            pytest.fail(f"hint is hardcoded back into a tooltip: {line.strip()[:100]}")


@pytest.mark.parametrize("page", _pages(), ids=lambda p: p.name)
def test_opt_in_matches_whether_the_page_has_a_run_button(page: Path):
    src = _read(page)
    if not MOUNTS_TOOLBAR.search(src):
        pytest.skip(f"{page.name} does not mount ExportToolbar")

    has_run = bool(RUN_BUTTON.search(src))
    opts_in = bool(OPT_IN.search(src))

    if has_run and not opts_in:
        pytest.fail(
            f"{page.name} has a Run button but does not pass `hasRunControl`, "
            "so its animation tooltips omit the one instruction that applies."
        )
    if opts_in and not has_run:
        pytest.fail(
            f"{page.name} passes `hasRunControl` but renders no '▶ Run' button, "
            "so its tooltips tell the reader to press a control that is not there."
        )


def test_exactly_the_expected_pages_opt_in():
    """Pins the current answer, so adding a page cannot quietly change it.

    Not redundant with the parametrised test: that one checks consistency, and
    two pages could consistently lose their Run buttons together.
    """
    opted = {p.name for p in _pages() if OPT_IN.search(_read(p))}
    assert opted == {"QuantumSecureE2E.tsx", "PaperDataExchange.tsx"}, (
        f"pages opting into the Run hint changed: {sorted(opted)}. If a page "
        "gained or lost a Run control this is expected -- update the set."
    )


def test_several_pages_mount_the_toolbar_without_a_run_button():
    """The condition that made the bug possible must still be represented.

    If every toolbar page ever gained a Run button, the conditional would be
    dead code and the tests above would pass trivially.
    """
    mounting = [p for p in _pages() if MOUNTS_TOOLBAR.search(_read(p))]
    without_run = [p.name for p in mounting if not RUN_BUTTON.search(_read(p))]
    assert len(mounting) >= 5, "too few pages mount the toolbar for this to be meaningful"
    assert without_run, (
        "every page mounting ExportToolbar now has a Run button, so the "
        "conditional hint is untested by real usage."
    )
