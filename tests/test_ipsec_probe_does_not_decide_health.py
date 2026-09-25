"""alice-ipsec's health check sends ESP traffic, and that traffic never decides health.

/vpn read `0 B / 0 pkt` under "established" because nothing on the host sent
anything through the tunnel -- the same reading the ipsec CI job treats as a
policy bypass. The health check now pings the peer through the tunnel. These
pin the two properties that make that safe:

  * the ping is best-effort (`|| true`): an echo lost in the gap between two
    CHILD_SAs must not mark the node unhealthy, since bob-ipsec and others
    wait on `service_healthy`;
  * the target is the configured peer, not a literal.
"""
from __future__ import annotations

from pathlib import Path

import yaml

COMPOSE = Path(__file__).resolve().parents[1] / "docker-compose.strongswan.yml"


def _svc(name: str) -> dict:
    return yaml.safe_load(COMPOSE.read_text())["services"][name]


def test_alice_ipsec_probes_the_tunnel_without_failing_on_it():
    test = _svc("alice-ipsec")["healthcheck"]["test"]
    cmd = test[1] if test[0] == "CMD-SHELL" else " ".join(test)
    assert "grep -q ML_KEM_768" in cmd, "the original health criterion is gone"
    assert "ping -c1" in cmd
    assert '"$$PEER_IP"' in cmd or "$PEER_IP" in cmd, "the probe must target the configured peer"
    assert "|| true" in cmd.split("ping", 1)[1], "a lost echo would mark the node unhealthy"


def test_the_probe_target_is_the_peer_address():
    env = _svc("alice-ipsec")["environment"]
    assert env["PEER_IP"] == "10.30.0.21"
