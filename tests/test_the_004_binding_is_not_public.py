"""The ETSI GS QKD 004 endpoint stays on the internal networks, and off by default.

The binding has no authentication, like ETSI GS QKD 014 on this stack and
`/internal/sync`: it is reachable only from qkd-net and mgmt-net, and on the
public host from qkd-net only (the cloud overlay takes the KMEs off mgmt-net,
where Caddy, the frontend and webui-backend sit, and takes webui-backend off
qkd-net; the backend reads the KMEs through kme-relay, which refuses it). Four
things keep it there, and each is checked:

  * no compose file publishes a KME port;
  * the frontend nginx forwards only /api/ (to webui-backend);
  * webui-backend has no route or proxy that reaches /etsi004 or /internal;
  * the public Caddy site proxies only to webui-frontend.

And the shipped config keeps the binding switched off: nothing on the public
demo drives it, and CI switches it on only for the contract test.
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml
from test_compose_env_is_read_by_something import _ComposeLoader

REPO = Path(__file__).resolve().parents[1]
KME_SERVICES = {"bb84-kme-a", "bb84-kme-b"}


def _compose_files() -> list[Path]:
    return sorted(REPO.glob("docker-compose*.yml")) + sorted((REPO / "deploy").glob("docker-compose*.yml"))


def test_no_compose_file_publishes_a_kme_port():
    for f in _compose_files():
        services = (yaml.load(f.read_text(), Loader=_ComposeLoader) or {}).get("services") or {}
        for name in (KME_SERVICES | {"kme-relay"}) & set(services):
            assert not (services[name] or {}).get("ports"), f"{f.name} publishes {name}"


def test_nginx_forwards_only_api():
    conf = (REPO / "services/webui-frontend/nginx.conf").read_text()
    targets = re.findall(r"proxy_pass\s+([^;]+);", conf)
    assert targets == ["http://webui-backend:8000"], targets
    assert "etsi004" not in conf and "/internal" not in conf


def test_webui_backend_does_not_reach_the_binding():
    src = (REPO / "services/webui-backend/app/main.py").read_text()
    assert "etsi004" not in src
    assert "/internal/" not in src


def test_caddy_proxies_only_to_the_frontend():
    caddy = (REPO / "deploy/Caddyfile").read_text()
    assert re.findall(r"reverse_proxy\s+(\S+)", caddy) == ["webui-frontend:80"]


def test_the_shipped_config_keeps_it_off():
    params = yaml.safe_load((REPO / "config/qkd_params.yaml").read_text())
    assert params["etsi004"]["endpoint_enabled"] is False


# ---- the public overlay keeps the KMEs off every internet-facing container ----
# mgmt-net is where Caddy, the frontend and webui-backend sit, and where a
# caddy.d/ drop-in on the public host attaches the containers of the other
# sites Caddy serves. The overlay takes the KMEs and pqc-validator off it and
# takes webui-backend off qkd-net, so nothing that answers the internet shares
# a network with the unauthenticated key API. The nodes reach the KMEs on
# qkd-net; webui-backend reads their status through kme-relay, which passes only
# the GET routes the backend uses, and reaches pqc-validator on backend-net.

class _OverrideLoader(yaml.SafeLoader):
    """Keeps Compose's `!override`, which replaces a mapping instead of merging it."""


class _Override(dict):
    pass


def _construct_tagged(loader, suffix, node):
    if isinstance(node, yaml.MappingNode):
        mapping = loader.construct_mapping(node, deep=True)
        return _Override(mapping) if suffix == "override" else mapping
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node, deep=True)
    return loader.construct_scalar(node)


_OverrideLoader.add_multi_constructor("!", _construct_tagged)


def _public_networks() -> dict[str, set[str]]:
    base = yaml.load((REPO / "docker-compose.yml").read_text(), Loader=_OverrideLoader)["services"]
    cloud = yaml.load((REPO / "deploy/docker-compose.cloud.yml").read_text(),
                      Loader=_OverrideLoader)["services"]
    out = {}
    for name in set(base) | set(cloud):
        nets = set((base.get(name) or {}).get("networks") or {})
        over = (cloud.get(name) or {}).get("networks")
        if isinstance(over, _Override):
            nets = set(over)
        elif over is not None:
            nets |= set(over)
        out[name] = nets
    return out


def test_the_public_overlay_keeps_the_kmes_off_the_internet_facing_network():
    nets = _public_networks()
    facing = nets["caddy"] | nets["webui-frontend"] | nets["webui-backend"]
    assert facing, "found no networks for Caddy, the frontend or the backend"
    for name in sorted(KME_SERVICES):
        shared = nets[name] & facing
        assert not shared, (f"{name} shares {sorted(shared)} with Caddy, the frontend "
                            "or webui-backend on the public host")
    for name in ("pqc-validator", "kme-relay"):
        shared = nets[name] & (nets["caddy"] | nets["webui-frontend"])
        assert not shared, f"{name} shares {sorted(shared)} with Caddy or the frontend on the public host"
    # What must still connect does, and only this way.
    assert nets["webui-backend"] & nets["kme-relay"], "webui-backend cannot reach kme-relay"
    assert nets["kme-relay"] & nets["bb84-kme-a"] & nets["bb84-kme-b"], "kme-relay cannot reach the KMEs"
    assert nets["webui-backend"] & nets["pqc-validator"], "webui-backend cannot reach pqc-validator"
    assert nets["webui-backend"] & nets["webui-frontend"], "the frontend cannot reach webui-backend"
    assert nets["alice"] & nets["bb84-kme-a"], "the WireGuard nodes cannot reach the KMEs"


# ---- kme-relay passes the backend's reads and nothing else -------------------
RELAY = REPO / "deploy/kme-relay.Caddyfile"
RELAY_PORTS = {"8081": "bb84-kme-a:8080", "8082": "bb84-kme-b:8080"}


def _relay_config() -> tuple[str, dict[str, str]]:
    """The global options block and each site block, comments removed."""
    lines = [ln for ln in RELAY.read_text().splitlines() if not ln.lstrip().startswith("#")]
    text = "\n".join(lines)
    glob = re.search(r"^\{\n(.*?)^\}", text, flags=re.M | re.S)
    sites = dict(re.findall(r"^:(\d+) \{\n(.*?)^\}", text, flags=re.M | re.S))
    return (glob.group(1) if glob else ""), sites


def _backend_kme_reads() -> set[str]:
    """The paths webui-backend GETs from a KME (KME_A_URL, KME_B_URL or a loop over them)."""
    src = (REPO / "services/webui-backend/app/main.py").read_text()
    return set(re.findall(r'client\.get\(f"\{(?:url|KME_A_URL|KME_B_URL)\}(/[^"?{]+)"', src))


def test_the_public_backend_reads_the_kmes_through_the_relay():
    cloud = yaml.load((REPO / "deploy/docker-compose.cloud.yml").read_text(),
                      Loader=_OverrideLoader)["services"]
    env = cloud["webui-backend"]["environment"]
    assert env["KME_A_URL"] == "http://kme-relay:8081"
    assert env["KME_B_URL"] == "http://kme-relay:8082"
    assert "./deploy/kme-relay.Caddyfile:/etc/caddy/Caddyfile:ro" in cloud["kme-relay"]["volumes"]


def test_the_relay_passes_only_the_reads_the_backend_makes():
    glob, sites = _relay_config()
    assert "admin off" in glob, "the relay's Caddy admin API must be off"
    assert set(sites) == set(RELAY_PORTS), sorted(sites)
    reads = _backend_kme_reads()
    assert reads, "found no KME reads in webui-backend"
    for port, upstream in RELAY_PORTS.items():
        body = sites[port]
        methods = re.findall(r"^\s*method\s+(.+)$", body, flags=re.M)
        paths = re.findall(r"^\s*path\s+(.+)$", body, flags=re.M)
        assert [m.split() for m in methods] == [["GET", "HEAD"]], (port, methods)
        assert len(paths) == 1, (port, paths)
        allowed = set(paths[0].split())
        assert not any("*" in p for p in allowed), f"{port}: a wildcard lets more than a listed path through"
        missing = reads - allowed
        assert not missing, f"{port}: webui-backend reads {sorted(missing)}, which the relay refuses"
        extra = allowed - reads - {"/health"}
        assert not extra, f"{port}: the relay passes {sorted(extra)}, which webui-backend does not read"
        assert re.findall(r"reverse_proxy\s+(\S+)", body) == [upstream], (port, body)
        assert re.search(r"^\s*handle\s*\{\s*respond 403\s*\}", body, flags=re.M), \
            f"{port}: anything that is not a listed read must get 403"


def test_the_override_check_sees_a_merge_as_a_merge():
    # Without `!override` Compose merges the overlay's networks into the base
    # ones, and the KME would stay on mgmt-net; the check must model that.
    doc = yaml.load("networks:\n  qkd-net: {}\n", Loader=_OverrideLoader)
    assert not isinstance(doc["networks"], _Override)
    doc = yaml.load("networks: !override\n  qkd-net: {}\n", Loader=_OverrideLoader)
    assert isinstance(doc["networks"], _Override)
