"""Packet and byte budgets quoted from the reference paper.

Source: P. Spooren, A. Neuhold, S. Ramacher, T. Huehn, "PQC-Enhanced QKD
Networks: A Layered Approach", arXiv:2604.05599 (CC BY 4.0), Table III and
sections IV-B / VI.

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

# Table III: per-phase handshake cost of one multi-hop cycle.
PHASE_BUDGETS: dict[int, dict[str, Any]] = {
    1: {"name": "Quantum Plane",
        "packets": 0, "bytes": 0,
        "period_s": None, "grace_s": 0,
        "description": "QKD device generates symmetric key material; "
                       "no IP-layer traffic in this phase."},
    2: {"name": "Arnika QKD key_ID exchange",
        "packets": 2, "bytes": 78,
        "period_s": 120, "grace_s": 180,
        "description": "Arnika fetches QKD key from local ETSI 014 KME and "
                       "negotiates the active key_ID with the neighbour Arnika."},
    3: {"name": "WireGuard hop handshake",
        "packets": 3, "bytes": 398,
        "period_s": 120, "grace_s": 60,
        "description": "Curve25519 + ChaCha20 handshake establishes the "
                       "QKD-secured hop tunnel; the QKD-derived PSK is mixed in."},
    4: {"name": "Rosenpass PQC handshake",
        "packets": 4, "bytes": 4772,
        "period_s": 120, "grace_s": 180,
        "description": "Classic McEliece + Kyber end-to-end PQC handshake "
                       "carried over the chain of QKD-secured WireGuard hops."},
    5: {"name": "Final data tunnel + Data Exchange",
        "packets": 0, "bytes": 0,    # variable, application-defined
        "period_s": 120, "grace_s": 60,
        "description": "Application data tunnel (WireGuard with ChaCha20-Poly1305) "
                       "uses a PSK derived from the Rosenpass output."},
}

TOTAL_HANDSHAKE_PACKETS = sum(p["packets"] for p in PHASE_BUDGETS.values())
TOTAL_HANDSHAKE_BYTES = sum(p["bytes"] for p in PHASE_BUDGETS.values())

# Mean end-to-end setup time reported for 10- and 100-hop chains. The pair is
# close together because setup is dominated by the per-hop handshakes running
# concurrently rather than by chain length.
MEAN_10_HOP_SETUP_S = 10.27
MEAN_100_HOP_SETUP_S = 10.62


def as_dict() -> dict[str, Any]:
    """The payload shape `/api/verify/paper-budgets` returns."""
    return {
        "phases": [{"phase": k, **v} for k, v in sorted(PHASE_BUDGETS.items())],
        "total_handshake_packets": TOTAL_HANDSHAKE_PACKETS,
        "total_handshake_bytes": TOTAL_HANDSHAKE_BYTES,
        "mean_10_hop_setup_s": MEAN_10_HOP_SETUP_S,
        "mean_100_hop_setup_s": MEAN_100_HOP_SETUP_S,
    }
