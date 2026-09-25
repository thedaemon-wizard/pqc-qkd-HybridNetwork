"""The paper's setup times live in two files; they must not drift apart.

`services/webui-backend/app/paper_budgets.py` owns MEAN_10_HOP_SETUP_S and
MEAN_100_HOP_SETUP_S, pinned against arXiv:2604.05599 Evaluation, Test 2 - Long Distance by
`tests/test_paper_budgets.py`. `services/webui-frontend/src/lib/sim/paperSim.ts`
restated the same two numbers as bare literals, with nothing comparing them.

One value with two homes and no test is the shape that produced most of the
defects corrected in this project: three key-pool copies, three BB84 default
sets, a threshold drawn at a literal while the protocol read a config. The
numbers happened to agree here -- this makes agreeing a requirement rather than
a coincidence.

Deliberately narrow: it compares the two SOURCES, not what a page renders. A
value can be right in both files and displayed wrongly, which is what checklist
row 4.7.5 is for.
"""
from __future__ import annotations

import importlib
import re
from pathlib import Path

import pytest
from conftest import load_service_app

ROOT = Path(__file__).resolve().parents[1]
PAPER_SIM = ROOT / "services" / "webui-frontend" / "src" / "lib" / "sim" / "paperSim.ts"

load_service_app("webui-backend", "webui_backend_app")
paper_budgets = importlib.import_module("webui_backend_app.paper_budgets")

NAMES = ["MEAN_10_HOP_SETUP_S", "MEAN_100_HOP_SETUP_S"]


def _typescript_constants() -> dict[str, float]:
    src = PAPER_SIM.read_text(encoding="utf-8")
    found = {}
    for name in NAMES:
        m = re.search(rf"export const {name}\s*=\s*([0-9.]+)\s*;", src)
        if m:
            found[name] = float(m.group(1))
    return found


def test_both_constants_are_declared_in_the_typescript_port():
    """Guard the guard: an inlined literal would make the comparison vacuous."""
    found = _typescript_constants()
    missing = [n for n in NAMES if n not in found]
    assert not missing, (
        f"{missing} not declared as exported constants in "
        f"{PAPER_SIM.relative_to(ROOT)}. If they were inlined back into the "
        "object literal, this test would silently stop comparing anything."
    )


@pytest.mark.parametrize("name", NAMES)
def test_typescript_matches_python(name):
    ts = _typescript_constants()[name]
    py = getattr(paper_budgets, name)
    assert ts == py, (
        f"{name}: paperSim.ts has {ts}, paper_budgets.py has {py}. "
        "These are literature values from arXiv:2604.05599 Evaluation, Test 2 - Long Distance -- change "
        "both to match the paper, never one to match the other."
    )


def test_no_stray_copies_of_the_literals_remain():
    """The values must not reappear as bare numbers somewhere else in the TS.

    Catches a future edit that adds `mean_10_hop_setup_s: 10.27` back into some
    other object rather than importing the constant.
    """
    src = PAPER_SIM.read_text(encoding="utf-8")
    # Strip the two declaration lines, then look for the digits again.
    stripped = re.sub(r"export const MEAN_1?0*0?_HOP_SETUP_S\s*=\s*[0-9.]+\s*;", "", src)
    stripped = re.sub(r"export const MEAN_\d+_HOP_SETUP_S\s*=\s*[0-9.]+\s*;", "", stripped)
    strays = [v for v in ("10.27", "10.62") if v in stripped]
    assert not strays, (
        f"{strays} appear as bare literals in {PAPER_SIM.name} outside their "
        "declaration. Import the constant instead."
    )


# ---------------------------------------------------------------------------
# Table 1 per phase. The two ports carry the same five-row table; they drifted
# once already (grace_s 180 against the paper's 60 s window), and nothing
# compared them, so a correction to one left the other reading the old value.
# ---------------------------------------------------------------------------
PHASE_FIELDS = ("packets", "bytes", "period_s", "grace_s")


def _typescript_phase_budgets() -> dict[int, dict[str, float | None]]:
    src = PAPER_SIM.read_text(encoding="utf-8")
    block = re.search(r"const PHASE_BUDGETS[^=]*=\s*\{(.*?)\n\};", src, re.S)
    assert block, f"PHASE_BUDGETS not found in {PAPER_SIM.name}"
    rows: dict[int, dict[str, float | None]] = {}
    for m in re.finditer(r"^\s*(\d+):\s*\{(.*?)description:", block.group(1), re.S | re.M):
        fields = {}
        for f in PHASE_FIELDS:
            v = re.search(rf"\b{f}:\s*(null|[0-9.]+)", m.group(2))
            assert v, f"phase {m.group(1)} has no {f} in {PAPER_SIM.name}"
            fields[f] = None if v.group(1) == "null" else float(v.group(1))
        rows[int(m.group(1))] = fields
    return rows


def test_both_ports_carry_the_same_phase_table():
    ts = _typescript_phase_budgets()
    py = {k: {f: (None if v[f] is None else float(v[f])) for f in PHASE_FIELDS}
          for k, v in paper_budgets.PHASE_BUDGETS.items()}
    assert sorted(ts) == sorted(py) == [1, 2, 3, 4, 5], (sorted(ts), sorted(py))
    diffs = [(k, f, ts[k][f], py[k][f]) for k in py for f in PHASE_FIELDS
             if ts[k][f] != py[k][f]]
    assert not diffs, (
        "paperSim.ts and paper_budgets.py disagree on Table 1 (phase, field, ts, py): "
        f"{diffs}. Change both to match the paper, never one to match the other.")


def test_every_grace_window_is_the_papers_sixty_seconds():
    """4.3 Fail-Safe Mechanism: 'every 120s, with a 60s grace window' for all
    three refreshing components; phase 1 has no refresh and so no window."""
    for k, v in paper_budgets.PHASE_BUDGETS.items():
        expected = 0 if v["period_s"] is None else 60
        assert v["grace_s"] == expected, (k, v["grace_s"])
