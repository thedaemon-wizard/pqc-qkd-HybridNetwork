"""The PQC half of every arnika PSK comes from the pinned arnika, not from a file.

Until the pin moved to upstream PR #51's head (f4cf9ba, 2026-09-24), arnika
read the PQC half of HKDF-SHA3-256(QKD || PQC) from a file: a Rosenpass sidecar
wrote it and PQC_PSK_FILE told arnika where. PR #51 removes that handover --
its INSTALL.md calls PQC_PSK_FILE "ignored" -- and has arnika agree the PQC key
with its peer itself, over PQC-HPKE (HPKE Base mode, RFC 9180, KEM
MLKEM1024-P384 from draft-ietf-hpke-pq), on the UDP channel it already uses for
the key_id. The guard this file replaces failed on exactly that pin bump, which
was its job; this one holds the deployment to what the new pin needs.

Derived from the pinned tree, so it skips without the submodule and runs in the
CI `go` job, which checks it out:

  * config.go reads PQC_ENABLED and no longer reads PQC_PSK_FILE, and the PQC
    reader package exists;
  * the MODE the deployment sets is one config.go accepts, and PQC_ENABLED is
    compared against the exact literal the deployment writes.

From this repository alone, so it runs everywhere:

  * nothing sets PQC_PSK_FILE -- a variable nothing reads is how the PQC half
    would drop out without an error anywhere;
  * every arnika instance runs PQC_ENABLED "true" and MODE QkdAndPqcRequired,
    both as shipped and as each example env file sets them;
  * the two peers of every pair agree on MODE, PQC_ENABLED, INTERVAL and any
    PQC_ROUND_* setting, which the pinned arnika requires to be identical on
    both ends (its docs/pqc-hpke.md, "Configuration Reference");
  * the entrypoints' own checks on ARNIKA_PSK and PQC_ENABLED are not here:
    tests/test_entrypoints_validate_their_input.py runs them under bash, which
    tests what they do rather than how they are written;
  * no arnika instance runs at a LOG_LEVEL other than info: the rotation lines
    every counter here reads are INFO records;
  * no arnika service is granted IPC_LOCK. With it, the pinned arnika's
    mlockall succeeds and pins its whole reserved heap arena, which upstream's
    own comment measures at about 1.2 GB per process; without it the lock is
    refused and arnika logs a warning and continues.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
from conftest import compose_env, compose_resolve, compose_services, load_compose, read_env_example

ROOT = Path(__file__).resolve().parents[1]
ARNIKA = ROOT / "submodules" / "arnika"
CONFIG_GO = ARNIKA / "config" / "config.go"

# The composition the lanes are started with: the base file first, then the
# overlays, merged per service in that order as `docker compose -f ... -f ...`
# merges them.
LANE_FILES = [ROOT / "docker-compose.yml", ROOT / "docker-compose.multihop.yml",
              ROOT / "docker-compose.strongswan.yml"]
ALL_COMPOSE = sorted(ROOT.glob("docker-compose*.yml")) + sorted((ROOT / "deploy").glob("docker-compose*.yml"))
EXAMPLE_ENV = [p for p in (ROOT / ".env.example", ROOT / "deploy" / ".env.example") if p.is_file()]

# The values the deployment runs every arnika instance with. MODE: both halves
# required, so a missing PQC key fails closed instead of degrading to QKD only.
WANT_MODE = "QkdAndPqcRequired"
WANT_PQC_ENABLED = "true"
WANT_LOG_LEVEL = "info"
# Settings the pinned arnika requires to be identical on both peers of a pair.
MUST_MATCH = ("ARNIKA_MODE", "PQC_ENABLED", "ARNIKA_INTERVAL",
              "PQC_ROUND_INTERVAL", "PQC_ROUND_TIMEOUT", "PQC_MAX_KEY_AGE")


SERVICES = compose_services(LANE_FILES)
ARNIKA_SERVICES = sorted(n for n, s in SERVICES.items() if "ARNIKA_PSK" in s["env"])
MAPPINGS = [("compose defaults", {})] + [(p.relative_to(ROOT).as_posix(), read_env_example(p)) for p in EXAMPLE_ENV]


def _pairs() -> set[tuple[str, str]]:
    """Peer pairs, from SERVER_ADDRESS and from alice's ARNIKA_EXTRA_PEERS."""
    pairs = set()
    for name in ARNIKA_SERVICES:
        env = SERVICES[name]["env"]
        host = str(compose_resolve(env.get("SERVER_ADDRESS", ""), {})).rsplit(":", 1)[0]
        if host in ARNIKA_SERVICES:
            pairs.add(tuple(sorted((name, host))))
        for entry in str(compose_resolve(env.get("ARNIKA_EXTRA_PEERS", "") or "", {})).split():
            peer = entry.split("@", 1)[0]
            if peer in ARNIKA_SERVICES:
                pairs.add(tuple(sorted((name, peer))))
    return pairs


PAIRS = sorted(_pairs())


# --------------------------------------------------------- the pinned tree --

def _pinned_config() -> str:
    if not CONFIG_GO.is_file():
        pytest.skip("arnika submodule not checked out")
    return CONFIG_GO.read_text(encoding="utf-8")


def test_the_pinned_arnika_agrees_the_pqc_key_itself():
    cfg = _pinned_config()
    assert '"PQC_ENABLED"' in cfg, (
        "the pinned arnika no longer reads PQC_ENABLED; the PQC-HPKE agreement "
        "this deployment relies on for the PQC half is gone or renamed")
    assert '"PQC_PSK_FILE"' not in cfg, (
        "the pinned arnika reads PQC_PSK_FILE again: the pin moved back before "
        "upstream PR #51, and the lanes no longer provide that file")
    assert (ARNIKA / "repositories" / "pqchpke" / "pqchpke.go").is_file(), (
        "repositories/pqchpke/ is missing from the pinned arnika")


def test_the_deployment_writes_the_literal_the_pinned_parser_compares():
    """PQC_ENABLED is on only for the exact string the parser compares with, so
    "True" or "1" would switch the PQC half off without an error."""
    m = re.search(r'getEnvOrDefault\("PQC_ENABLED",\s*"[^"]*"\)\s*==\s*"([^"]*)"', _pinned_config())
    assert m, "config.go no longer compares PQC_ENABLED with a literal; re-read how it parses"
    assert m.group(1) == WANT_PQC_ENABLED


def test_the_deployed_mode_is_one_the_pinned_parser_accepts():
    modes = set(re.findall(r'config\.Mode != "(\w+)"', _pinned_config()))
    assert modes, "config.go no longer lists the accepted MODE values"
    assert WANT_MODE in modes, f"{WANT_MODE} is not accepted by the pinned arnika: {sorted(modes)}"


# ------------------------------------------------------------ this repository --

def test_the_scan_sees_every_arnika_instance_and_pair():
    """Guard the guard: an overlay that stops parsing would empty both lists."""
    assert {"alice", "bob", "alice-ipsec", "bob-ipsec", "charlie"} <= set(ARNIKA_SERVICES)
    assert ("alice-ipsec", "bob-ipsec") in PAIRS
    assert ("alice", "bob") in PAIRS
    assert ("alice", "charlie") in PAIRS


def _setting_lines(path: Path) -> list[str]:
    """Lines that can set a variable: comments dropped, whatever the syntax."""
    return [ln for ln in path.read_text(encoding="utf-8", errors="replace").splitlines()
            if not ln.lstrip().startswith("#")]


def test_nothing_sets_pqc_psk_file():
    hits = []
    for path in ALL_COMPOSE:
        for name, svc in (load_compose(path).get("services") or {}).items():
            if isinstance(svc, dict) and "PQC_PSK_FILE" in compose_env(svc):
                hits.append(f"{path.relative_to(ROOT)}: service {name}")
    candidates = [*EXAMPLE_ENV, *sorted((ROOT / "deploy").glob("*.sh"))]
    candidates += [p for p in sorted((ROOT / "nodes").rglob("*")) if p.is_file()]
    for path in candidates:
        for line in _setting_lines(path):
            if "PQC_PSK_FILE" in line:
                hits.append(f"{path.relative_to(ROOT)}: {line.strip()[:80]}")
    assert not hits, (
        "PQC_PSK_FILE is still set, but the pinned arnika ignores it -- the PQC "
        "half is agreed over PQC-HPKE now, so this variable promises a key "
        "source nothing reads:\n  " + "\n  ".join(hits))


@pytest.mark.parametrize("label,mapping", MAPPINGS, ids=[m[0] for m in MAPPINGS])
@pytest.mark.parametrize("name", ARNIKA_SERVICES)
def test_every_instance_runs_both_halves_required(name, label, mapping):
    env = SERVICES[name]["env"]
    enabled = env.get("PQC_ENABLED")
    assert enabled is not None, f"{name}: PQC_ENABLED is not set"
    assert isinstance(enabled, str), (
        f"{name}: PQC_ENABLED is the YAML {type(enabled).__name__} {enabled!r}; quote it, "
        "compose passes the string on and arnika compares it with a literal")
    assert compose_resolve(enabled, mapping) == WANT_PQC_ENABLED, f"{name} ({label}): PQC_ENABLED"
    mode = env.get("ARNIKA_MODE")
    assert mode is not None, f"{name}: ARNIKA_MODE is not set"
    assert compose_resolve(mode, mapping) == WANT_MODE, f"{name} ({label}): ARNIKA_MODE"


@pytest.mark.parametrize("label,mapping", MAPPINGS, ids=[m[0] for m in MAPPINGS])
@pytest.mark.parametrize("pair", PAIRS, ids=["-".join(p) for p in PAIRS])
def test_both_peers_of_a_pair_agree(pair, label, mapping):
    a, b = (SERVICES[n]["env"] for n in pair)
    differ = {k: (compose_resolve(a.get(k), mapping), compose_resolve(b.get(k), mapping)) for k in MUST_MATCH
              if compose_resolve(a.get(k), mapping) != compose_resolve(b.get(k), mapping)}
    assert not differ, (
        f"{pair[0]} and {pair[1]} ({label}) disagree on {differ}. The pinned arnika "
        "requires these to be identical on both peers; a mismatch fails every PQC "
        "round or every role election rather than degrading.")


def _psk_entrypoints() -> list[Path]:
    return [p for p in sorted((ROOT / "nodes").rglob("entrypoint.sh"))
            if any("ARNIKA_PSK" in ln for ln in _setting_lines(p))]


def test_no_instance_runs_at_a_log_level_that_hides_the_rotation_lines():
    bad = []
    for name in ARNIKA_SERVICES:
        value = SERVICES[name]["env"].get("LOG_LEVEL")
        if value is not None and str(compose_resolve(value, {})).lower() != WANT_LOG_LEVEL:
            bad.append(f"{name}: LOG_LEVEL {value!r}")
    assign = re.compile(r"\bLOG_LEVEL=(\"?)([^\"\s;]*)\1")
    for path in _psk_entrypoints():
        for line in _setting_lines(path):
            for m in assign.finditer(line):
                if str(compose_resolve(m.group(2), {})).lower() != WANT_LOG_LEVEL:
                    bad.append(f"{path.relative_to(ROOT)}: {line.strip()}")
    assert not bad, (
        "arnika logs every rotation at INFO; a higher level empties "
        "/api/vpn/ppk-rotations and the CI rotation count:\n  " + "\n  ".join(bad))


@pytest.mark.parametrize("name", ARNIKA_SERVICES)
def test_no_arnika_service_is_granted_ipc_lock(name):
    svc = SERVICES[name]["service"]
    caps = {str(c).upper().removeprefix("CAP_") for c in svc.get("cap_add") or []}
    assert "IPC_LOCK" not in caps and "ALL" not in caps, f"{name}: cap_add {sorted(caps)}"
    assert svc.get("privileged") is not True, f"{name} is privileged, which includes IPC_LOCK"
