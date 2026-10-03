"""Exactly one end of each Rosenpass pair initiates, and the pin makes that hold.

The WireGuard lane's Rosenpass exchange runs inside wg0, between the two
nodes' wg0 addresses. Only the end with the lower wg0 address is given an
`endpoint` (nodes/alice/entrypoint.sh, rp_peer_entry); the other end is given
the bare peer name, answers to the address the initiator's packets come from,
and never initiates. With an endpoint on both ends, every cold start left the
two ends on different wg1 PSKs until the next exchange 120 s later: both
ends' first messages waited in wg0 until arnika's first rotation keyed it and
then crossed.

That the answering end never initiates is not a setting. It is how rosenpass
v0.2.3 behaves, and nothing in its configuration promises it:

  * PeerPtr::poll (rosenpass/src/protocol.rs) asks for an initiation only while
    `initiation_requested` is false, and sets it to true when it asks;
  * the only statement that sets it back to false is in IniHsPtr::insert, which
    runs only when a handshake is actually initiated;
  * the event loop (rosenpass/src/app_server.rs) sends an initiation through
    the tx_maybe_with macro, which does nothing for a peer without an
    endpoint. So a peer with no endpoint asks once at startup, the request is
    dropped, the flag stays set, and it never asks again -- even after it has
    learnt the initiator's address from the first exchange.

A rosenpass bump can change any of that without a single deployment file
changing, and simultaneous initiation would come back silently. So this file
pins the rosenpass commit whose source was read, checks the three facts above
in the checked-out source, and runs the entrypoint's rp_peer_entry under bash
for every Rosenpass pair the compose files define.
"""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest
from conftest import compose_resolve, compose_services

ROOT = Path(__file__).resolve().parents[1]
ENTRYPOINT = ROOT / "nodes" / "alice" / "entrypoint.sh"
ROSENPASS = ROOT / "submodules" / "rosenpass"
PROTOCOL_RS = ROSENPASS / "rosenpass" / "src" / "protocol.rs"
APP_SERVER_RS = ROSENPASS / "rosenpass" / "src" / "app_server.rs"
LANE_FILES = [ROOT / "docker-compose.yml", ROOT / "docker-compose.multihop.yml"]

# rosenpass v0.2.3. The responder behaviour above was read in this commit.
ROSENPASS_PIN = "512fe426be9281366d92a910d391fe8ddd72bd10"
# git's mode for a gitlink, a submodule rather than a blob.
GITLINK_MODE = "160000"
RP_PORT = "9997"
BASH_TIMEOUT_S = 30
GIT_TIMEOUT_S = 60

RECHECK = (
    "Before moving the pin, re-read in the new rosenpass: (1) protocol.rs, "
    "PeerPtr::poll and every assignment to `initiation_requested` -- a peer must "
    "still ask for an initiation once and never again until IniHsPtr::insert "
    "runs; (2) app_server.rs, the tx_maybe_with macro and the SendInitiation "
    "arm of the event loop -- a peer without an endpoint must still send "
    "nothing, including after `current_endpoint` is learnt from a received "
    "message. If either changed, the answering end may initiate too, and the "
    "two ends of a pair can again end a cold start on different wg1 PSKs "
    "(see rp_peer_entry in nodes/alice/entrypoint.sh). Then update "
    "ROSENPASS_PIN here.")


# ------------------------------------------------------------------ pin --

def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, timeout=GIT_TIMEOUT_S)


def test_the_rosenpass_pin_is_the_commit_whose_responder_was_read():
    """Read from the index, which is where the next commit's pin is prepared."""
    if _git("rev-parse", "--is-inside-work-tree").returncode != 0:
        pytest.skip("not a git checkout, so there is no gitlink to read")
    out = _git("ls-files", "-s", "submodules/rosenpass")
    fields = out.stdout.split()
    assert out.returncode == 0 and len(fields) >= 2 and fields[0] == GITLINK_MODE, (
        f"submodules/rosenpass is no longer a submodule in the index: {out.stdout.strip()!r}")
    assert fields[1] == ROSENPASS_PIN, (
        f"the rosenpass pin moved from {ROSENPASS_PIN} (v0.2.3) to {fields[1]}. {RECHECK}")


# ------------------------------------------------------ pinned source --

def _source(path: Path) -> str:
    if not path.is_file():
        pytest.skip("rosenpass submodule not checked out")
    head = subprocess.run(["git", "-C", str(ROSENPASS), "rev-parse", "HEAD"], capture_output=True,
                          text=True, timeout=GIT_TIMEOUT_S)
    if head.returncode == 0:
        assert head.stdout.strip() == ROSENPASS_PIN, (
            f"submodules/rosenpass is checked out at {head.stdout.strip()}, not the pin {ROSENPASS_PIN}; "
            "run `git submodule update submodules/rosenpass` before reading its source")
    return path.read_text(encoding="utf-8")


def _fn_body(src: str, signature: str) -> str:
    """From `signature` to the next `fn ` at the same or a shallower indent."""
    start = src.index(signature)
    indent = src.rfind("\n", 0, start) + 1
    width = start - indent
    nxt = re.compile(rf"^ {{0,{width}}}(pub )?fn ", re.M)
    m = nxt.search(src, start + len(signature))
    return src[start:m.start() if m else len(src)]


def test_the_initiation_request_is_cleared_only_when_a_handshake_is_initiated():
    src = _source(PROTOCOL_RS)
    cleared = [m.start() for m in re.finditer(r"initiation_requested\s*=\s*false", src)]
    assert len(cleared) == 1, f"`initiation_requested = false` appears {len(cleared)} times. {RECHECK}"
    insert = _fn_body(src, "pub fn insert<'a>(")
    assert "initiation_requested = false" in insert, (
        f"the one statement that clears `initiation_requested` is no longer in IniHsPtr::insert. {RECHECK}")
    assert len(re.findall(r"initiation_requested\s*=\s*true", src)) == 1, RECHECK
    assert "Wait::immediate_unless(self.get(srv).initiation_requested)" in src, (
        f"PeerPtr::poll no longer gates the initiation on `initiation_requested`. {RECHECK}")


def test_an_initiation_is_sent_only_to_a_peer_with_an_endpoint():
    src = _source(APP_SERVER_RS)
    macro = re.search(r"macro_rules! tx_maybe_with \{(.*?)\n        \}", src, re.S)
    assert macro, f"app_server.rs no longer defines tx_maybe_with. {RECHECK}"
    assert re.search(r"if p\.get_app\(self\)\.endpoint\(\)\.is_some\(\) \{", macro.group(1)), (
        f"tx_maybe_with no longer skips a peer without an endpoint. {RECHECK}")
    assert re.search(r"SendInitiation\(peer\) => tx_maybe_with!\(", src), (
        f"the event loop no longer sends an initiation through tx_maybe_with. {RECHECK}")


# ------------------------------------------------ the entrypoint's rule --

def _function(name: str) -> str:
    m = re.search(rf"^{name}\(\) \{{.*?^\}}", ENTRYPOINT.read_text(encoding="utf-8"), re.M | re.S)
    assert m, f"{ENTRYPOINT.relative_to(ROOT)} no longer defines {name}()"
    return m.group(0)


def rp_peer_entry(own_wg0: str, peer: str, peer_wg0: str, port: str = RP_PORT) -> subprocess.CompletedProcess:
    """The entrypoint's own rp_peer_entry, run under bash."""
    script = "\n".join(["set -euo pipefail", _function("ipv4_as_int"), _function("rp_peer_entry"),
                        'rp_peer_entry "$1" "$2"'])
    return subprocess.run(["bash", "-c", script, "bash", peer, peer_wg0], capture_output=True, text=True,
                          env={"PATH": os.environ["PATH"], "WG_LOCAL_IP": own_wg0, "RP_PEER_PORT": port},
                          timeout=BASH_TIMEOUT_S)


ENTRY_CASES = [
    # own wg0, peer name, peer wg0, expected entry
    ("10.0.0.1", "bob", "10.0.0.2", f"bob@10.0.0.2:{RP_PORT}"),
    ("10.0.0.2", "alice", "10.0.0.1", "alice"),
    ("10.0.0.1", "charlie", "10.0.0.3", f"charlie@10.0.0.3:{RP_PORT}"),
    ("10.0.0.3", "alice", "10.0.0.1", "alice"),
    # Compared as numbers, not as text: "10.0.0.10" sorts before "10.0.0.9".
    ("10.0.0.9", "far", "10.0.0.10", f"far@10.0.0.10:{RP_PORT}"),
    ("10.0.0.10", "near", "10.0.0.9", "near"),
    ("10.0.1.255", "next", "10.0.2.0", f"next@10.0.2.0:{RP_PORT}"),
]


@pytest.mark.parametrize("own,peer,peer_wg0,want", ENTRY_CASES,
                         ids=[f"{c[0]}-vs-{c[2]}" for c in ENTRY_CASES])
def test_only_the_lower_wg0_address_gets_an_endpoint(own, peer, peer_wg0, want):
    out = rp_peer_entry(own, peer, peer_wg0)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == want, (
        f"{own} facing {peer} at {peer_wg0} gave {out.stdout.strip()!r}, expected {want!r}: the lower wg0 "
        "address initiates, the other end answers")


def test_a_peer_with_this_nodes_own_address_is_refused():
    out = rp_peer_entry("10.0.0.1", "self", "10.0.0.1")
    assert out.returncode != 0 and not out.stdout.strip(), "a peer on this node's own wg0 address was accepted"


def test_every_rosenpass_peer_is_built_by_rp_peer_entry():
    """No other assignment to RP_PEERS could slip an endpoint past the rule."""
    code = [ln for ln in ENTRYPOINT.read_text(encoding="utf-8").splitlines() if not ln.lstrip().startswith("#")]
    assigns = [ln.strip() for ln in code if re.match(r"\s*(export\s+)?RP_PEERS\+?=", ln)]
    assert assigns, f"{ENTRYPOINT.relative_to(ROOT)} no longer builds RP_PEERS"
    bad = [ln for ln in assigns if "$(rp_peer_entry " not in ln]
    assert not bad, f"RP_PEERS is assigned without rp_peer_entry: {bad}"


def _rosenpass_pairs() -> list[tuple[str, str, dict]]:
    """Every pair of Rosenpass nodes the lane files define, with their wg0 addresses."""
    services = compose_services(LANE_FILES)
    nodes = {n: s["env"] for n, s in services.items() if "RP_LISTEN_PORT" in s["env"]}
    wg0 = {n: str(compose_resolve(env.get("WG_LOCAL_IP"), {})) for n, env in nodes.items()}
    pairs = set()
    for name, env in nodes.items():
        peers = {str(compose_resolve(env.get("WG_PEER_ENDPOINT", ""), {})).split(":", 1)[0]}
        peers |= {e.split("@", 1)[0] for e in str(compose_resolve(env.get("WG1_EXTRA_PEERS") or "", {})).split()}
        pairs |= {tuple(sorted((name, p))) for p in peers if p in nodes}
    return [(a, b, wg0) for a, b in sorted(pairs)]


PAIRS = _rosenpass_pairs()


def test_the_scan_sees_both_rosenpass_pairs():
    """Guard the guard: an overlay that stops parsing would empty the list."""
    assert {(a, b) for a, b, _ in PAIRS} >= {("alice", "bob"), ("alice", "charlie")}


@pytest.mark.parametrize("a,b,wg0", PAIRS, ids=[f"{a}-{b}" for a, b, _ in PAIRS])
def test_exactly_one_end_of_each_pair_initiates(a, b, wg0):
    got = {a: rp_peer_entry(wg0[a], b, wg0[b]).stdout.strip(), b: rp_peer_entry(wg0[b], a, wg0[a]).stdout.strip()}
    initiators = [n for n, entry in got.items() if "@" in entry]
    assert len(initiators) == 1, f"{a} and {b}: entries {got}; exactly one end must have an endpoint"
    lower = min((a, b), key=lambda n: tuple(int(x) for x in wg0[n].split(".")))
    assert initiators == [lower], f"{initiators[0]} initiates, but {lower} has the lower wg0 address"
