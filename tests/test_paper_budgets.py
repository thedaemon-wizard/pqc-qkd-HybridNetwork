"""Pin the packet budgets quoted from arXiv:2604.05599 Table 1.

These numbers are the project's claim about what the paper says, and
`/api/verify/paper-budgets` serves them as verification evidence. Nothing
guarded them before: they lived inside a backend orchestrator that the UI
stopped calling when the pages moved client-side, so an edit would have
changed what the project asserts the literature reports with no test failing.

The point of these assertions is that they should fail if someone "fixes" the
constants to match whatever the simulator currently produces. That is exactly
backwards -- the simulator is compared against the paper, not the reverse.
"""
from __future__ import annotations

import importlib

import pytest
from conftest import load_service_app

# Same helper the other webui-backend test uses. Importing `app` directly via
# sys.path collides with it: two tests would register different packages under
# the same top-level name and collection fails.
load_service_app("webui-backend", "webui_backend_app")
paper_budgets = importlib.import_module("webui_backend_app.paper_budgets")


def test_per_phase_values_match_table_iii():
    """Phase-by-phase handshake cost, Table 1."""
    expected = {
        1: (0, 0),        # quantum plane: no IP-layer traffic
        2: (2, 78),       # arnika key_ID exchange
        3: (3, 398),      # WireGuard hop handshake
        4: (4, 4772),     # Rosenpass PQC handshake
        5: (0, 0),        # data tunnel: application-defined, not a fixed budget
    }
    actual = {k: (v["packets"], v["bytes"]) for k, v in paper_budgets.PHASE_BUDGETS.items()}
    assert actual == expected


def test_totals_are_the_published_figures():
    """9 packets / 5248 bytes for one full multi-hop handshake cycle."""
    assert paper_budgets.TOTAL_HANDSHAKE_PACKETS == 9
    assert paper_budgets.TOTAL_HANDSHAKE_BYTES == 5248


def test_totals_are_derived_not_typed_twice():
    """The totals must be the sum of the phases, not independently maintained.

    If someone edits a phase and hand-edits the total to match, this still
    passes -- but if they edit only one of the two, it catches it.
    """
    assert paper_budgets.TOTAL_HANDSHAKE_PACKETS == sum(
        p["packets"] for p in paper_budgets.PHASE_BUDGETS.values())
    assert paper_budgets.TOTAL_HANDSHAKE_BYTES == sum(
        p["bytes"] for p in paper_budgets.PHASE_BUDGETS.values())


def test_mean_setup_times():
    """Section VI: 10- and 100-hop chains differ by well under a second.

    Setup is dominated by per-hop handshakes running concurrently rather than
    by chain length, so a large gap between these two would mean the figures
    had been transcribed wrongly.
    """
    assert paper_budgets.MEAN_10_HOP_SETUP_S == pytest.approx(10.27)
    assert paper_budgets.MEAN_100_HOP_SETUP_S == pytest.approx(10.62)
    assert abs(paper_budgets.MEAN_100_HOP_SETUP_S
               - paper_budgets.MEAN_10_HOP_SETUP_S) < 1.0


def test_as_dict_shape_matches_the_endpoint_contract():
    """`/api/verify/paper-budgets` and the WebUI depend on these exact keys."""
    d = paper_budgets.as_dict()
    assert set(d) == {"phases", "total_handshake_packets", "total_handshake_bytes",
                      "paper_total_packets", "paper_total_bytes",
                      "mean_10_hop_setup_s", "mean_100_hop_setup_s"}
    assert [p["phase"] for p in d["phases"]] == [1, 2, 3, 4, 5]
    for p in d["phases"]:
        assert {"phase", "name", "packets", "bytes",
                "period_s", "grace_s", "description"} <= set(p)


def test_the_totals_are_transcribed_independently_of_the_table():
    """`packets_match` on /verify must be able to fail.

    It used to compare `sum(PHASE_BUDGETS)` against `TOTAL_HANDSHAKE_PACKETS`,
    which is defined as `sum(PHASE_BUDGETS)`. Editing any per-phase figure moved
    both sides together, so the flag was true by construction and the /verify
    page displayed a check that could not detect anything.

    The paper totals are now literals, so a per-phase edit breaks the match --
    which is the only thing that makes displaying it worth doing.
    """
    import ast
    import inspect

    src = inspect.getsource(paper_budgets)
    tree = ast.parse(src)
    literals = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
            if name in ("PAPER_TOTAL_PACKETS", "PAPER_TOTAL_BYTES"):
                literals[name] = node.value

    assert set(literals) == {"PAPER_TOTAL_PACKETS", "PAPER_TOTAL_BYTES"}
    for name, value in literals.items():
        assert isinstance(value, ast.Constant), (
            f"{name} must be a literal transcribed from the paper, not a "
            f"computed expression -- otherwise the match check compares the "
            f"table against itself"
        )

    # And they must equal the sums today, or the table disagrees with the paper.
    assert paper_budgets.PAPER_TOTAL_PACKETS == paper_budgets.TOTAL_HANDSHAKE_PACKETS == 9
    assert paper_budgets.PAPER_TOTAL_BYTES == paper_budgets.TOTAL_HANDSHAKE_BYTES == 5248


def test_a_per_phase_edit_breaks_the_paper_match():
    """The failure mode the flag exists to catch."""
    original = paper_budgets.PHASE_BUDGETS[3]["packets"]
    try:
        paper_budgets.PHASE_BUDGETS[3]["packets"] = original + 1
        recomputed = sum(p["packets"] for p in paper_budgets.PHASE_BUDGETS.values())
        assert recomputed != paper_budgets.PAPER_TOTAL_PACKETS
    finally:
        paper_budgets.PHASE_BUDGETS[3]["packets"] = original


# ---------------------------------------------------------------------------
# The citation itself, not just the numbers.
#
# Every file in this repository cited these budgets as "arXiv:2604.05599 §IV-B
# Table III", and two files cited "section VI" for the setup times. The paper
# has no Roman-numeral sections at all and exactly ONE table. The numbers were
# right the whole time -- 3+2+4 packets and 398+78+4772 bytes -- but a reader
# following the citation had nowhere to go.
#
# The paper is redistributed in this repository under CC BY 4.0, so the check
# can read the actual source rather than trusting a transcription.
# ---------------------------------------------------------------------------
import re
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAPER_PDF = ROOT / "references" / "PQC-Enhanced_QKD_Networks_A_Layered_Approach.pdf"

# Section names as the arXiv (LNCS-style) full version actually prints them.
REAL_SECTIONS = ["Introduction", "Related Work", "Implementation",
                 "Evaluation", "Conclusion"]
WRONG_CITATIONS = ["Table III", "§IV-B", "IV-B", "section VI"]

# Files that RECORD the correction, and so have to quote the wrong citation in
# order to say what was wrong. Every one of them must also name the right
# anchor, checked below -- otherwise the exemption becomes the place a bad
# citation hides. Keep this small; a source file has no business being here.
#
# This list exists because the first version of this guard failed on the very
# commit that introduced it: the checklist row describing the fix quotes the
# string the row forbids. The same trap caught the SeQUeNCe backend guard
# (`depolarizing_rate`) and the log-export guard (`logService`).
DOCUMENTS_THE_CORRECTION = {
    "tests/test_paper_budgets.py",
    "VERIFICATION_CHECKLIST.md",
    "docs/roadmap.md",
}
RIGHT_ANCHOR = "Table 1"


def _paper_text() -> str:
    if not PAPER_PDF.exists():
        pytest.skip(f"{PAPER_PDF.name} not present")
    if not shutil.which("pdftotext"):
        pytest.skip("pdftotext (poppler-utils) not installed")
    return subprocess.run(
        ["pdftotext", str(PAPER_PDF), "-"],
        capture_output=True, text=True, check=True,
    ).stdout


def test_the_paper_has_one_table_and_it_is_table_1():
    """Read the shipped PDF: no Roman numerals, one table, named sections."""
    text = _paper_text()

    captions = re.findall(r"^\s*Table\s+(\S+)\.", text, re.MULTILINE)
    assert captions, "no table caption found; has the PDF been replaced?"
    assert set(captions) == {"1"}, (
        f"expected exactly one table numbered 1, found captions {captions}. "
        "Citations across this repository say 'Table III'."
    )
    assert not re.search(r"^\s*(?:II|III|IV|V|VI)\.\s", text, re.MULTILINE), (
        "the paper appears to use Roman-numeral sections after all; the "
        "citations in this repository were changed on the basis that it does not"
    )
    for heading in REAL_SECTIONS:
        assert re.search(rf"^{re.escape(heading)}$", text, re.MULTILINE), (
            f"expected a section headed {heading!r}"
        )


def test_the_budgets_are_the_numbers_printed_in_table_1():
    """Derive the totals from the paper instead of trusting the transcription.

    Table 1 lists three components; this repository splits the same traffic
    across phases, so the per-component rows are what can be compared.
    """
    text = _paper_text()
    rows = {}
    for comp in ("WireGuard", "Arnika", "Rosenpass"):
        m = re.search(rf"^{comp}\s*\n\s*(\d+)\s*\n\s*(\d+)\s*$", text, re.MULTILINE)
        assert m, f"could not read the {comp} row of Table 1"
        rows[comp] = (int(m.group(1)), int(m.group(2)))

    assert rows == {"WireGuard": (3, 398), "Arnika": (2, 78), "Rosenpass": (4, 4772)}
    assert sum(p for p, _ in rows.values()) == paper_budgets.PAPER_TOTAL_PACKETS
    assert sum(b for _, b in rows.values()) == paper_budgets.PAPER_TOTAL_BYTES


def test_no_tracked_file_cites_a_section_the_paper_does_not_have():
    """Text guard, so this holds even where pdftotext is unavailable."""
    tracked = subprocess.run(
        ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True,
    ).stdout.split()

    offenders = []
    for rel in tracked:
        p = ROOT / rel
        if not p.is_file() or p.suffix in {".pdf", ".png", ".jpg", ".gif", ".webm"}:
            continue
        try:
            body = p.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if rel in DOCUMENTS_THE_CORRECTION:
            if any(bad in body for bad in WRONG_CITATIONS):
                assert RIGHT_ANCHOR in body, (
                    f"{rel} is exempt because it documents the correction, but "
                    f"it quotes a wrong citation without naming {RIGHT_ANCHOR!r}. "
                    "The exemption is for explaining the fix, not for carrying "
                    "the defect."
                )
            continue
        for bad in WRONG_CITATIONS:
            if bad in body:
                offenders.append(f"{rel}: {bad!r}")

    assert not offenders, (
        "arXiv:2604.05599 has no Roman-numeral sections and exactly one table "
        "(Table 1, in Evaluation / Test 1 - Prototype Validation). The setup "
        "times 10.27 s and 10.62 s are in Test 2 - Long Distance, and the "
        "240-720 s cascade is in the Fail-Safe Mechanism subsection of "
        "Implementation. Wrong citations:\n  " + "\n  ".join(offenders)
    )
