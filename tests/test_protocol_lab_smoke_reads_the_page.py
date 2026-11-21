"""What scripts/protocol_lab_smoke.py reads from the page's source is still there.

The browser check in CI's frontend job compares the page against literals and
scenario ids it reads from the frontend's source, and against the supply line's
wording. If one of those goes, that check fails too, but only after a build and
three minutes of Chrome, and it says "could not run". This fails in the Python
job instead and names what went. It also holds the CI steps that run the check
and show that it can fail.
"""
from __future__ import annotations

import importlib.util
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "protocol_lab_smoke.py"
NETWORKS = ROOT / "services/webui-frontend/src/lib/sim/protocolLab/publishedNetworks.ts"
CI = ROOT / ".github" / "workflows" / "ci.yml"
TAIL = " (derived, at 256 bits per key from this project's config)."


def _smoke():
    spec = importlib.util.spec_from_file_location("protocol_lab_smoke", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_the_literals_it_compares_against_are_in_the_source():
    lit = _smoke().page_literals()
    assert lit["crash"] == "This page failed to render"
    assert lit["band"] == "Simulation, not the running stack."
    assert lit["routeOnly"].startswith("Route only:")


def test_every_replay_it_holds_to_its_source_is_a_scenario_of_the_page():
    ids = set(re.findall(r'\bid: "([a-z0-9-]+)"', NETWORKS.read_text(encoding="utf-8")))
    assert set(_smoke().REPLAYS) <= ids


def test_the_supply_parser_reads_each_wording_the_page_prints():
    supply_of = _smoke().supply_of
    head = "Supply: this route's slowest hop, "
    # Thuringia: a reported mean with its spread, and a key slower than one a second.
    assert supply_of(head + "SND-ERF, reports average 12.7 ± 10.3 bps; at that rate it makes "
                     "one 256-bit key about every 20 s" + TAIL) == ("SND-ERF", 12.7, 256, 0.05)
    # Tokyo: a qualified value with a unit prefix.
    assert supply_of(head + "K1-K2, reports about 2.1 kbps; at that rate it makes about 8.2 keys/s"
                     + TAIL) == ("K1-K2", 2100.0, 256, 8.2)
    # SECOQC: the source's own words around the number, and "bit/s".
    assert supply_of(head + "ERD-BRT, reports almost equal to the SECOQC criterion of 1 kbit/s; at that "
                     "rate it makes about 3.9 keys/s" + TAIL) == ("ERD-BRT", 1000.0, 256, 3.9)
    assert supply_of("Counting: keys") is None


def test_ci_runs_it_and_shows_that_it_can_fail():
    text = CI.read_text(encoding="utf-8")
    assert "run: python3 scripts/protocol_lab_smoke.py --no-sandbox\n" in text
    assert re.search(r"protocol_lab_smoke\.py --no-sandbox --only networks --policy \"default-src 'self'\"\n"
                     r"\s+rc=\$\?\n\s+test \"\$rc\" -eq 1 ", text)
