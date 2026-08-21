"""Pin the packet budgets quoted from arXiv:2604.05599 Table III.

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
    """Phase-by-phase handshake cost, Table III."""
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
