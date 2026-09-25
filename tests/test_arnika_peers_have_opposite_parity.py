"""Every pair of peered arnika instances has ARNIKA_IDs of opposite parity.

arnika elects the per-interval primary with
    IsPrimary = ((HMAC-SHA256(ARNIKA_PSK, interval)[0]) XOR ARNIKA_ID) & 1 == 0
(submodules/arnika/config/config.go). Only bit 0 of the ID matters, so two
peers whose IDs differ but share a parity take the same role every interval
and neither ever receives the other's key_ID. The multihop leg paired alice's
second instance (ID 1) with charlie (ID 3) -- different, and both odd. The
comments said only that the IDs must "differ".
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# (instance A's ID variable, instance B's ID variable, where they pair)
PAIRS = [
    ("ARNIKA_ID_ALICE", "ARNIKA_ID_BOB", "WireGuard lane, docker-compose.yml"),
    # alice's extra instance for the charlie leg runs with ARNIKA_ID_ALICE
    # (nodes/alice/entrypoint.sh passes ARNIKA_ID="$ARNIKA_ID").
    ("ARNIKA_ID_ALICE", "ARNIKA_ID_CHARLIE", "multihop leg, docker-compose.multihop.yml"),
    ("ARNIKA_ID_ALICE_IPSEC", "ARNIKA_ID_BOB_IPSEC", "IPsec lane, docker-compose.strongswan.yml"),
]


def _compose_defaults() -> dict[str, int]:
    out: dict[str, int] = {}
    for f in ROOT.glob("docker-compose*.yml"):
        for var, val in re.findall(r"\$\{(ARNIKA_ID_\w+):-(\d+)\}", f.read_text()):
            assert out.get(var, int(val)) == int(val), f"{var} has two defaults"
            out[var] = int(val)
    return out


def _env_example() -> dict[str, int]:
    return {k: int(v) for k, v in
            re.findall(r"^(ARNIKA_ID_\w+)=(\d+)\s*$", (ROOT / ".env.example").read_text(), re.M)}


def test_compose_defaults_pair_opposite_parities():
    ids = _compose_defaults()
    for a, b, where in PAIRS:
        assert a in ids and b in ids, f"{where}: no default for {a} or {b}"
        assert ids[a] % 2 != ids[b] % 2, f"{where}: {a}={ids[a]} and {b}={ids[b]} share a parity"


def test_env_example_agrees_with_compose():
    env, compose = _env_example(), _compose_defaults()
    for var, val in env.items():
        if var in compose:
            assert val == compose[var], f"{var}: .env.example {val}, compose default {compose[var]}"


def test_the_extra_instance_really_reuses_alices_id():
    """The premise of the charlie pair: if the entrypoint ever gives the extra
    instance its own ID, this pairing has to be re-derived."""
    src = (ROOT / "nodes/alice/entrypoint.sh").read_text()
    assert 'ARNIKA_ID="$ARNIKA_ID" \\' in src
