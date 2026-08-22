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
