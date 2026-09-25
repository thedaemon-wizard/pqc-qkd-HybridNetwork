"""Packet and byte budgets quoted from the reference paper.

Source: P. Spooren, A. Neuhold, S. Ramacher, T. Huehn, "PQC-Enhanced QKD
Networks: A Layered Approach", arXiv:2604.05599 (CC BY 4.0), Table 1 (Evaluation,
Test 1 - Prototype Validation) and the Fail-Safe Mechanism subsection of
Implementation.

These are LITERATURE VALUES, not measurements. `/api/verify/paper-budgets`
serves them so the WebUI can compare a live run against the published figures,
which is the whole point of the /verify page -- so they must not be quietly
edited to match whatever the simulator currently produces.

They used to live in `paper_flow.py`, a backend orchestrator that drove the
/paper-flow page over a WebSocket before that page moved client-side. The
orchestrator is gone; the constants are not, because the verification endpoint
still needs them. Extracting them here is what made deleting the orchestrator
possible: importing it merely for a dict meant a dead 400-line module had to
keep booting with the application.

`tests/test_paper_budgets.py` pins the totals so a careless edit fails a test
rather than silently changing what the project claims the paper says.
"""

from __future__ import annotations

from typing import Any

# Table 1 ("Packets and Traffic per Handshake or Key Negotiation"), split into
# this repository's five phases. The paper itself does not use the word
# "phase": it numbers the components (1)-(4) in 4.3 and Figure 3 calls them
# stages. Phase 1 is its (1), 2 its (2), 3 and 4 its (3) (the WireGuard hop
# and the Rosenpass exchange carried over it), and 5 its (4).
#
# `grace_s` is the paper's grace WINDOW, which the Fail-Safe Mechanism
# subsection gives as 60 s for all three components: keys are refreshed "every
# 120s, with a 60s grace window before terminating a connection (WireGuard) or
# injecting random keys (Arnika, Rosenpass)". Arnika and Rosenpass read 180
# here, which is period + grace -- the time until a missed refresh bites -- in
# a field named for the window alone.
PHASE_BUDGETS: dict[int, dict[str, Any]] = {
    1: {"name": "Quantum Plane",
        "packets": 0, "bytes": 0,
        "period_s": None, "grace_s": 0,
        "description": "QKD device generates symmetric key material; "
                       "no IP-layer traffic in this phase."},
    2: {"name": "Arnika QKD key_ID exchange",
        "packets": 2, "bytes": 78,
        "period_s": 120, "grace_s": 60,
        "description": "Arnika fetches QKD key from local ETSI 014 KME and "
                       "negotiates the active key_ID with the neighbour Arnika."},
    3: {"name": "WireGuard hop handshake",
        "packets": 3, "bytes": 398,
        "period_s": 120, "grace_s": 60,
        "description": "Curve25519 + ChaCha20 handshake establishes the "
                       "QKD-secured hop tunnel; the QKD-derived PSK is mixed in."},
    4: {"name": "Rosenpass PQC handshake",
        "packets": 4, "bytes": 4772,
        "period_s": 120, "grace_s": 60,
        "description": "Classic McEliece + Kyber end-to-end PQC handshake "
                       "carried over the chain of QKD-secured WireGuard hops."},
    5: {"name": "Final data tunnel + Data Exchange",
        "packets": 0, "bytes": 0,    # variable, application-defined
        "period_s": 120, "grace_s": 60,
        "description": "Application data tunnel (WireGuard with ChaCha20-Poly1305) "
                       "uses a PSK derived from the Rosenpass output."},
}

# Table 1's three rows, transcribed separately from PHASE_BUDGETS above and
# keyed by the component name the paper prints, with the phase of this
# repository's split that carries the same traffic.
#
# These rows are the independent side of `/api/verify/paper-budgets`. The
# comparison used to be of TOTALS: the sum of PHASE_BUDGETS against 9 / 5248,
# described here as "the totals AS PRINTED IN THE PAPER". Table 1 prints no
# total. It prints these three rows, so 9 / 5248 were hand sums of them, and a
# pair of compensating edits (one phase up, another down) left both totals
# unchanged and the check green. Comparing row by row is what can catch that;
# tests/test_paper_budgets.py reads the rows back out of the paper text.
TABLE_1_ROWS: dict[str, dict[str, int]] = {
    "WireGuard": {"phase": 3, "packets": 3, "bytes": 398},
    "Arnika": {"phase": 2, "packets": 2, "bytes": 78},
    "Rosenpass": {"phase": 4, "packets": 4, "bytes": 4772},
}

# The SUM of Table 1's rows, computed here. Not a figure the paper states:
# kept because `/api/verify/paper-budgets` has always reported a total, and
# named for what it is in that response (`paper_totals_source`).
PAPER_TOTAL_PACKETS = sum(r["packets"] for r in TABLE_1_ROWS.values())
PAPER_TOTAL_BYTES = sum(r["bytes"] for r in TABLE_1_ROWS.values())
PAPER_TOTALS_SOURCE = "sum of the three Table 1 rows, computed; Table 1 prints no total"

TOTAL_HANDSHAKE_PACKETS = sum(p["packets"] for p in PHASE_BUDGETS.values())
TOTAL_HANDSHAKE_BYTES = sum(p["bytes"] for p in PHASE_BUDGETS.values())

# Mean end-to-end setup time reported for 10- and 100-hop chains. The pair is
# close together because setup is dominated by the per-hop handshakes running
# concurrently rather than by chain length.
MEAN_10_HOP_SETUP_S = 10.27
MEAN_100_HOP_SETUP_S = 10.62


def as_dict() -> dict[str, Any]:
    """The literature values, as this module holds them.

    NOT the shape `/api/verify/paper-budgets` returns -- that endpoint wraps
    this, renaming the totals to `paper_total_*` and adding its own
    `computed_total_*` and match flags. An earlier version of this docstring
    claimed the two were the same, which is the kind of small untruth that
    sends a reader to the wrong place.
    """
    return {
        "phases": [{"phase": k, **v} for k, v in sorted(PHASE_BUDGETS.items())],
        "table1_rows": [{"component": c, **r} for c, r in TABLE_1_ROWS.items()],
        "total_handshake_packets": TOTAL_HANDSHAKE_PACKETS,
        "total_handshake_bytes": TOTAL_HANDSHAKE_BYTES,
        "paper_total_packets": PAPER_TOTAL_PACKETS,
        "paper_total_bytes": PAPER_TOTAL_BYTES,
        "mean_10_hop_setup_s": MEAN_10_HOP_SETUP_S,
        "mean_100_hop_setup_s": MEAN_100_HOP_SETUP_S,
    }
