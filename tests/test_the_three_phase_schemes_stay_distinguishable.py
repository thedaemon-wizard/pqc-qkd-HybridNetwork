"""Three unrelated numbering schemes were all called "phase".

  build phases        0, 2-4, 8-14   this project's milestones, docs/phases.md
  protocol phases     1-5            THE PAPER'S, arXiv:2604.05599 Table 1
  /e2e orchestration  1-4            this project's own invention

A reader seeing "Phase 8" in the docs and "Phase 5" in the UI had no way to
know they were unrelated. The instruction to remove the labels was given four
times across successive rounds and never actioned, because the reason not to
was never recorded -- so it kept coming back.

The paper's scheme cannot be renamed. `paper_budgets.py` quotes "Table 1:
per-phase handshake cost", `/paper-flow` reproduces that table per phase, and
`tests/test_paper_budgets.py` pins the totals. Putting this project's
vocabulary between a reader and the source it claims to reproduce would be a
worse defect than the collision.

So: /e2e's scheme -- ours alone -- became "step", and /paper-flow keeps the
word but qualifies it. This file stops either half from drifting back.
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


def test_paper_flow_keeps_the_papers_word_but_qualifies_it():
    src = _read(PAPER)
    # Keeping the word is the point -- assert it is still there.
    assert "phase" in src.lower(), (
        "/paper-flow no longer uses the paper's own term for its own table"
    )
    assert "paper phase 5" in src, "the payload panel no longer says whose phase 5"
    assert re.search(r"paper'?s 5 protocol phases", src), (
        "the sequence diagram title no longer attributes the numbering"
    )
    # And it must not have been renamed away.
    assert "5-Phase Sequence Diagram (paper" not in src


def test_the_papers_terminology_is_still_what_the_backend_quotes():
    # The premise for refusing to rename. If the quote changes, the decision
    # needs revisiting rather than silently surviving.
    assert "per-phase handshake cost" in _read(BUDGETS), (
        "paper_budgets.py no longer quotes the paper as saying 'per-phase'; "
        "re-check whether the protocol scheme still has to keep that word"
    )


def test_the_decision_is_written_down():
    # The whole reason the instruction recurred four times. A fix with no
    # recorded reasoning gets re-litigated.
    src = _read(ROADMAP)
    assert "three unrelated schemes" in src
    for term in ("Build phases", "Protocol phases", "orchestration"):
        assert term in src, f"the decision record no longer names {term}"
