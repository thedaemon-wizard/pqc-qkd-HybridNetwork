"""What scripts/spa_tabs_smoke.py reads from the frontend's source is still there.

The every-tab check in CI's frontend job leaves the shared-gallery checkbox
alone by its label, knows the server-log export by its tooltip and an empty
CSV by what the exporter writes, and measures what a tab left behind on a tab
that runs nothing. If one of those moves, the check either stops running
("could not run", after a build and minutes of Chrome) or, worse for the
gallery, stops leaving it alone. This fails in the Python job instead and
names what moved. It also holds the CI steps that run the check and show that
it can fail.
"""
from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "spa_tabs_smoke.py"
SRC = ROOT / "services/webui-frontend/src"
CI = ROOT / ".github" / "workflows" / "ci.yml"


def _smoke():
    sys.path.insert(0, str(SCRIPT.parent))  # it imports csp_smoke and protocol_lab_smoke beside it
    spec = importlib.util.spec_from_file_location("spa_tabs_smoke", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_the_literals_it_reads_are_in_the_source():
    lit = _smoke().page_literals()
    assert lit["crash"] == "This page failed to render"
    assert lit["gallery"] == "Also save a copy to the shared gallery"
    assert lit["exportFailed"] == "export failed:"
    assert lit["serverLog"] == "Download rotating server log"
    assert lit["emptyCsv"] == "# empty"


def test_the_toolbar_has_the_three_recording_selects_it_sets_once():
    assert _smoke().toolbar_selects() == [
        "Animation duration (seconds)", "WebM frame rate (fps)", "GIF frame rate (fps)"]


def test_the_quiet_tab_is_a_route_that_starts_nothing():
    """`leave` measures what a left tab still runs on QUIET, against zero."""
    smoke = _smoke()
    app = (SRC / "App.tsx").read_text(encoding="utf-8")
    assert f'<Route path="{smoke.QUIET}" element={{<HIL />}} />' in app
    hil = (SRC / "pages" / "HIL.tsx").read_text(encoding="utf-8")
    for starts in ("setInterval", "setTimeout", "requestAnimationFrame", "WebSocket", "usePoll", "fetch("):
        assert starts not in hil, f"{smoke.QUIET} now uses {starts}: pick another quiet tab"


def test_every_export_button_it_presses_is_one_the_toolbar_draws():
    toolbar = (SRC / "components" / "ExportToolbar.tsx").read_text(encoding="utf-8")
    for label in _smoke().EXPORTS:
        assert re.search(rf">\s*{re.escape(label)}\s*<", toolbar), f"no {label} button in ExportToolbar.tsx"


def test_what_it_never_presses_matches_the_labels_it_must_not():
    smoke = _smoke()
    never = re.compile(smoke.NOT_PRESSED)
    writes = re.compile(smoke.WRITES, re.I)
    for label in ("Logs", "PNG", "JSON", "CSV", "WebM (HQ)", "GIF", "Download plot as a PNG"):
        assert never.match(label), label
    for label in ("restart", "Start", "stop", "Delete", "Remove this export"):
        assert writes.search(label), label
    for label in ("Run", "Step", "Reset", "Restart the round", "Optimize μ / ν (client-side)"):
        assert not never.match(label) and (not writes.search(label) or label.startswith("Restart ")), label


def test_ci_runs_it_and_shows_that_it_can_fail():
    text = CI.read_text(encoding="utf-8")
    assert "run: python3 scripts/spa_tabs_smoke.py --no-sandbox\n" in text
    assert re.search(r"spa_tabs_smoke\.py --no-sandbox --only tabs --policy \"default-src 'self'\"\n"
                     r"\s+rc=\$\?\n\s+test \"\$rc\" -eq 1 ", text)
