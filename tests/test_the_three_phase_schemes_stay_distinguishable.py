"""Three unrelated numbering schemes were all called "phase".

  build phases        0, 2-4, 8-14   this project's milestones, docs/phases.md
  protocol phases     1-5            this project's split of the paper's
                                     stages (1)-(4), arXiv:2604.05599 4.3 and
                                     Figure 3, used to lay out Table 1
  /e2e orchestration  1-4            this project's own invention

A reader seeing "Phase 8" in the docs and "Phase 5" in the UI had no way to
know they were unrelated.

This file used to say the protocol scheme was THE PAPER'S and could not be
renamed, because paper_budgets.py "quotes 'Table 1: per-phase handshake
cost'". Checked against the paper on 2026-09-25, that was wrong: the paper
never uses the word "phase". Table 1 is captioned "Packets and Traffic per
Handshake or Key Negotiation", and the components are numbered (1)-(4) and
called stages. The five-way split is this repository's.

So: /e2e's scheme became "step", and /paper-flow keeps "phase" only as its own
label, next to the paper's stage numbers so the two cannot be confused. This
file stops either half from drifting back.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "services" / "webui-frontend" / "src"

E2E = FRONTEND / "pages" / "QuantumSecureE2E.tsx"
PAPER = FRONTEND / "pages" / "PaperDataExchange.tsx"
BUDGETS = ROOT / "services" / "webui-backend" / "app" / "paper_budgets.py"
ROADMAP = ROOT / "docs" / "roadmap.md"


def _read(p: Path) -> str:
    assert p.is_file(), f"{p.relative_to(ROOT)} is missing"
    return p.read_text(encoding="utf-8")


def test_e2e_calls_its_own_scheme_a_step():
    src = _read(E2E)
    assert "Active step:" in src, "/e2e went back to calling its own scheme a phase"
    assert "Step history" in src
    assert "Active phase:" not in src


def test_paper_flow_names_the_papers_stages_next_to_its_own_phases():
    src = _read(PAPER)
    assert "paper stage (4)" in src, (
        "the payload panel no longer says which of the paper's stages phase 5 is")
    assert "splitting the paper's stages (1)-(4)" in src, (
        "the sequence diagram title no longer says the five phases are this "
        "page's split of the paper's four stages")
    # The attribution that was wrong: the paper has no phase 5.
    assert "paper phase" not in src.lower()
    assert not re.search(r"paper'?s 5 protocol phases", src)


def test_the_backend_quotes_table_1_by_its_real_caption():
    src = _read(BUDGETS)
    assert "Packets and Traffic per Handshake or Key Negotiation" in src, (
        "paper_budgets.py no longer quotes Table 1's caption")
    assert "per-phase handshake cost" not in src, (
        "the invented caption is back; the paper does not say 'phase'")


def test_the_decision_is_written_down():
    # The whole reason the instruction recurred four times. A fix with no
    # recorded reasoning gets re-litigated.
    src = _read(ROADMAP)
    assert "three unrelated schemes" in src
    for term in ("Build phases", "Protocol phases", "orchestration"):
        assert term in src, f"the decision record no longer names {term}"
