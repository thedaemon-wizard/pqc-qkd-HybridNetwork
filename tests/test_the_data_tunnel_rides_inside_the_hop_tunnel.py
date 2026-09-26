"""The WireGuard data tunnel rides inside the QKD-keyed hop tunnel.

The WireGuard lane runs two interfaces per node, in the layering of arXiv
2604.05599: wg0 is the hop tunnel, whose PSK arnika writes as HKDF-SHA3-256 over
the QKD key and a PQC-HPKE key; Rosenpass (Classic McEliece 460896 + Kyber512)
runs through wg0 and keys wg1, the end-to-end data tunnel, through its own
WireGuard output. wg1's peer endpoint is the peer's wg0 address, so wg1's
packets -- and the Rosenpass exchange -- travel inside wg0.

That layering is a property of two nodes' settings agreeing, and nothing at
runtime complains when they do not:

  * a wg1 endpoint on the peer's container name or wan-net address still
    handshakes, over the plain network, and the QKD layer then protects nothing
    on the data path;
  * a wg1 address inside wg0's subnet gives the kernel two routes for one
    prefix;
  * a wg1 port that differs from the one the peer dials, or a default that
    changed on one side only, is a tunnel that never comes up on a fresh
    deployment while an old .env keeps it working elsewhere.

So this reads docker-compose.yml the way compose does and checks the pair. The
multihop overlay's charlie leg is one-sided by design -- only alice faces
charlie -- so the pair is compared in the base file alone, and each extra wg1
peer is checked against that peer's own settings instead.

The file handover from Rosenpass to arnika is gone with the arnika pin
(f4cf9ba, upstream PR #51): arnika agrees its own PQC key now. Its volumes
(`pqc-psk-*`) and its variable (PQC_PSK_FILE) must be gone too, while the
Rosenpass identity keys (`rosenpass-keys-*`) and the WireGuard keypairs
(`wg-keys-*`, which now hold wg0's and wg1's) keep persisting across recreates,
or every recreate would mint keys the peer's copy in /shared no longer matches.
"""
from __future__ import annotations

import ipaddress
import re
from pathlib import Path

import pytest
from conftest import compose_env, compose_resolve, compose_services, load_compose, read_env_example

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "docker-compose.yml"
LANE_FILES = [BASE, ROOT / "docker-compose.multihop.yml", ROOT / "docker-compose.strongswan.yml"]
ALL_COMPOSE = sorted(ROOT.glob("docker-compose*.yml")) + sorted((ROOT / "deploy").glob("docker-compose*.yml"))
EXAMPLE_ENV = [p for p in (ROOT / ".env.example", ROOT / "deploy" / ".env.example") if p.is_file()]
ENTRYPOINT = ROOT / "nodes" / "alice" / "entrypoint.sh"

# The data tunnel's variables in the shared .env surface, and the default each
# one carries wherever compose interpolates it. wg1 sits in its own /24 next to
# wg0's, and listens ten ports above wg0 so the two cannot share a socket.
WG1_DEFAULTS = {
    "WG1_ALICE_IP": "10.0.1.1",
    "WG1_BOB_IP": "10.0.1.2",
    "WG1_LISTEN_PORT_ALICE": "51830",
    "WG1_LISTEN_PORT_BOB": "51831",
}
# Rosenpass's UDP port, on each node's wg0 address.
RP_PORT_DEFAULT = "9997"

NODES = ("alice", "bob")
PEER = {"alice": "bob", "bob": "alice"}
OWN_IP = {"alice": "WG1_ALICE_IP", "bob": "WG1_BOB_IP"}
OWN_PORT = {"alice": "WG1_LISTEN_PORT_ALICE", "bob": "WG1_LISTEN_PORT_BOB"}
# Swapping the two nodes' names in a variable reference turns one node's
# settings into the other's.
_MIRROR = re.compile(r"ALICE|BOB|alice|bob")
_SWAP = {"ALICE": "BOB", "BOB": "ALICE", "alice": "bob", "bob": "alice"}
_REF = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)")

SERVICES = compose_services(LANE_FILES)
# The alice/bob pair as docker-compose.yml defines it, before any overlay.
BASE_SERVICES = compose_services([BASE])
MAPPINGS = [("compose defaults", {})] + [(p.relative_to(ROOT).as_posix(), read_env_example(p)) for p in EXAMPLE_ENV]


def _env(node: str) -> dict:
    return SERVICES[node]["env"]


def _refs(value) -> set[str]:
    return set(_REF.findall(value)) if isinstance(value, str) else set()


def _wg1_keys(node: str, services: dict | None = None) -> dict[str, str]:
    """This node's environment entries that involve the data tunnel."""
    env = (services or SERVICES)[node]["env"]
    return {k: v for k, v in env.items()
            if isinstance(v, str) and (_refs(v) & set(WG1_DEFAULTS) or k.startswith("WG1_"))}


def _wg0_address(node: str) -> str:
    return str(compose_resolve(_env(node).get("WG_LOCAL_IP"), {}))


# ------------------------------------------------------------------- wg1 --

def test_both_nodes_define_the_data_tunnel():
    for node in NODES:
        keys = _wg1_keys(node)
        assert keys, f"{node} has no wg1 setting in docker-compose.yml"
        used = set().union(*(_refs(v) for v in keys.values()))
        missing = sorted(set(WG1_DEFAULTS) - used)
        assert not missing, f"{node} never refers to {missing}"


@pytest.mark.parametrize("var", sorted(WG1_DEFAULTS))
def test_each_wg1_variable_has_one_default_everywhere(var):
    """A default that differs between two interpolations is two deployments."""
    text = "\n".join(p.read_text(encoding="utf-8") for p in ALL_COMPOSE)
    defaults = set(re.findall(r"\$\{" + var + r":?-([^}]*)\}", text))
    assert defaults, f"{var} is never given a default in the compose files"
    assert defaults == {WG1_DEFAULTS[var]}, f"{var} defaults to {sorted(defaults)}"
    for path in EXAMPLE_ENV:
        example = read_env_example(path)
        if var in example:
            assert example[var] == WG1_DEFAULTS[var], (
                f"{path.relative_to(ROOT)} sets {var}={example[var]}, the compose "
                f"default is {WG1_DEFAULTS[var]}")


def _skeleton(value: str) -> str:
    """The literal text around the references: separators, prefix lengths."""
    return re.sub(r"\$\{[^}]*\}", "${}", value)


def test_alice_and_bob_mirror_each_other():
    """Every wg1 entry of bob's is alice's with the two names swapped.

    Compared in docker-compose.yml, where the pair is defined: the multihop
    overlay gives alice alone a WG1_EXTRA_PEERS entry for charlie, and bob
    has no counterpart by design (see the WG1_EXTRA_PEERS test below).
    Compared on the variables referred to and on the literal text around them;
    the defaults inside the references are held by the test above.
    """
    a, b = _wg1_keys("alice", BASE_SERVICES), _wg1_keys("bob", BASE_SERVICES)
    assert set(a) == set(b), f"wg1 settings only on one node: {sorted(set(a) ^ set(b))}"
    for key, value in a.items():
        mirrored = _MIRROR.sub(lambda m: _SWAP[m.group()], value)
        assert _refs(b[key]) == _refs(mirrored), (
            f"{key}: alice refers to {sorted(_refs(value))}, bob to {sorted(_refs(b[key]))}; "
            f"bob's should be alice's with the names swapped: {sorted(_refs(mirrored))}")
        assert _skeleton(b[key]) == _skeleton(mirrored), (
            f"{key}: alice {value!r} and bob {b[key]!r} differ in more than the names")


def _wg1_extra_entries() -> list[tuple[str, str, str, str]]:
    """(node, peer name, port value, ip value) for every WG1_EXTRA_PEERS entry.

    An entry is `name@<wg1 port>/<wg1 ip>`; the values keep their `${...}`.
    """
    out = []
    for node, svc in sorted(SERVICES.items()):
        for entry in str(svc["env"].get("WG1_EXTRA_PEERS") or "").split():
            name, _, rest = entry.partition("@")
            port, _, ip = rest.partition("/")
            out.append((node, name, port, ip))
    return out


WG1_EXTRA = _wg1_extra_entries()


def test_the_scan_sees_the_multihop_wg1_leg():
    """Guard the guard: an overlay that stops parsing would empty the list."""
    assert ("alice", "charlie") in {(n, p) for n, p, _, _ in WG1_EXTRA}


@pytest.mark.parametrize("node,peer,port,ip", WG1_EXTRA, ids=[f"{n}-{p}" for n, p, _, _ in WG1_EXTRA])
def test_each_extra_wg1_peer_refers_to_that_peers_own_settings(node, peer, port, ip):
    """The port and address a node dials for an extra wg1 peer are the ones
    that peer listens on and holds: the same variables, the same defaults."""
    assert peer in SERVICES, f"{node}'s WG1_EXTRA_PEERS names {peer!r}, which is no service"
    theirs = SERVICES[peer]["env"]
    for mine, own_key in ((port, "WG1_LISTEN_PORT"), (ip, "WG1_LOCAL_IP")):
        assert _refs(mine), f"{node}'s WG1_EXTRA_PEERS entry for {peer} has a literal {mine!r}, not a variable"
        assert _refs(mine) == _refs(theirs.get(own_key)), (
            f"{node} dials {peer} with {sorted(_refs(mine))}, but {peer}'s {own_key} is "
            f"{theirs.get(own_key)!r}")
        for label, mapping in MAPPINGS:
            assert compose_resolve(mine, mapping) == compose_resolve(theirs.get(own_key), mapping), (
                f"{node} and {peer} resolve {own_key} differently under {label}")
    wg0_peers = {e.partition("@")[0] for e in str(SERVICES[node]["env"].get("WG_EXTRA_PEERS") or "").split()}
    assert peer in wg0_peers, (
        f"{node} has a wg1 leg to {peer} but no wg0 leg, so that wg1 would have no hop tunnel to run in")


def _assigned_prefix(script: str, var: str) -> int:
    """The prefix length the entrypoint gives `var`'s address: a literal
    `"${VAR}/24"`, or `"${VAR}/${NAME}"` with a top-level `NAME=<digits>`."""
    m = re.search(r'"\$\{?' + var + r'\}?/(?:(\d+)|\$\{?([A-Za-z_][A-Za-z0-9_]*)\}?)"', script)
    assert m, f"{ENTRYPOINT.relative_to(ROOT)} no longer assigns {var} as <address>/<prefix>"
    if m.group(1):
        return int(m.group(1))
    const = re.search(r"^" + m.group(2) + r"=(\d+)\s*$", script, re.M)
    assert const, f"{ENTRYPOINT.relative_to(ROOT)} uses /${{{m.group(2)}}} without a top-level numeric assignment"
    return int(const.group(1))


def test_the_data_tunnel_has_its_own_subnet():
    script = ENTRYPOINT.read_text(encoding="utf-8")
    wg1_prefix = _assigned_prefix(script, "WG1_LOCAL_IP")
    wg0_prefix = _assigned_prefix(script, "WG_LOCAL_IP")
    wg1 = {n: ipaddress.ip_address(WG1_DEFAULTS[OWN_IP[n]]) for n in NODES}
    net = ipaddress.ip_network(f"{wg1['alice']}/{wg1_prefix}", strict=False)
    assert wg1["bob"] in net, f"alice and bob are not in one /{wg1_prefix}: {wg1}"
    assert wg1["alice"] != wg1["bob"]
    for node in NODES:
        hop = ipaddress.ip_address(_wg0_address(node))
        assert hop not in net, f"{node}'s wg0 address {hop} is inside the data tunnel's {net}"
    hop_net = ipaddress.ip_network(f"{_wg0_address('alice')}/{wg0_prefix}", strict=False)
    assert _wg0_address("bob") in {str(a) for a in hop_net.hosts()}, f"bob's wg0 address is outside {hop_net}"
    assert not net.overlaps(hop_net), f"wg1 {net} overlaps wg0 {hop_net}"


def test_the_data_tunnel_does_not_share_the_hop_tunnels_port():
    for node in NODES:
        wg0_port = str(compose_resolve(_env(node).get("WG_LISTEN_PORT"), {}))
        assert WG1_DEFAULTS[OWN_PORT[node]] != wg0_port, f"{node}: wg0 and wg1 both on {wg0_port}"


@pytest.mark.parametrize("node", NODES)
def test_the_wg1_endpoint_is_the_peers_wg0_address(node):
    """The whole point of the layering: wg1's packets must enter wg0."""
    peer = PEER[node]
    peer_port_var = OWN_PORT[peer]
    port_ref = re.compile(r"\$\{" + peer_port_var + r"[^}]*\}")
    carriers = {k: v for k, v in _env(node).items() if isinstance(v, str) and port_ref.search(v)}
    assert carriers, f"{node} never refers to {peer_port_var}, so it cannot dial {peer}'s wg1"
    want_host = _wg0_address(peer)
    for key, value in carriers.items():
        # Split at the colon before the port reference, not at the last colon:
        # `${X:-d}` carries one of its own.
        port = port_ref.search(value)
        host = value[:port.start() - 1] if port.start() > 0 else ""
        if port.end() == len(value) and host and value[port.start() - 1] == ":":
            got = compose_resolve(host, {})
            assert got == want_host, (
                f"{node}'s {key} dials {got}, but {peer}'s wg0 address is {want_host}. "
                "Anything else reaches the peer outside the hop tunnel.")
            continue
        # A bare port: the entrypoint joins it with the peer's wg0 address.
        assert port_ref.fullmatch(value), f"{node}'s {key} is neither host:port nor a port: {value}"
        assert compose_resolve(_env(node).get("WG_PEER_IP"), {}) == want_host
        script = ENTRYPOINT.read_text(encoding="utf-8")
        joined = re.search(r"\$\{?WG_PEER_IP\}?:\$\{?" + re.escape(key) + r"\b", script)
        assert joined, (
            f"{node}'s {key} is a bare port, and {ENTRYPOINT.relative_to(ROOT)} does not "
            "join it with WG_PEER_IP, the peer's wg0 address")


def test_rosenpass_uses_one_port_on_both_nodes():
    for node in NODES:
        value = _env(node).get("RP_LISTEN_PORT")
        assert compose_resolve(value, {}) == RP_PORT_DEFAULT, f"{node}: RP_LISTEN_PORT {value!r}"
    assert _env("alice").get("RP_LISTEN_PORT") == _env("bob").get("RP_LISTEN_PORT")


# ---------------------------------------------------------------- volumes --

def _mounts(svc: dict) -> list[str]:
    out = []
    for v in svc.get("volumes") or []:
        out.append(str(v.get("source", "")) if isinstance(v, dict) else str(v).split(":", 1)[0])
    return out


def test_no_service_mounts_a_pqc_psk_volume_or_sets_pqc_psk_file():
    hits = []
    for path in ALL_COMPOSE:
        doc = load_compose(path)
        for name in doc.get("volumes") or {}:
            if str(name).startswith("pqc-psk"):
                hits.append(f"{path.relative_to(ROOT)}: volume {name}")
        for name, svc in (doc.get("services") or {}).items():
            if not isinstance(svc, dict):
                continue
            hits += [f"{path.relative_to(ROOT)}: {name} mounts {m}"
                     for m in _mounts(svc) if m.startswith("pqc-psk")]
            if "PQC_PSK_FILE" in compose_env(svc):
                hits.append(f"{path.relative_to(ROOT)}: {name} sets PQC_PSK_FILE")
    assert not hits, (
        "the Rosenpass-to-arnika file handover is gone at the arnika pin, so "
        "these carry a key nothing reads:\n  " + "\n  ".join(hits))


@pytest.mark.parametrize("node", NODES)
def test_the_node_keys_still_persist(node):
    mounts = _mounts(SERVICES[node]["service"])
    for volume in (f"rosenpass-keys-{node}", f"wg-keys-{node}", "node-pubkeys"):
        assert volume in mounts, f"{node} no longer mounts {volume}"
    declared = load_compose(BASE).get("volumes") or {}
    assert f"rosenpass-keys-{node}" in declared and f"wg-keys-{node}" in declared
