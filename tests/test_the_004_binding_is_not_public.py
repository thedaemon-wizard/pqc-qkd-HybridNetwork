"""The ETSI GS QKD 004 endpoint stays on the internal networks, and off by default.

The binding has no authentication, like ETSI GS QKD 014 on this stack and
`/internal/sync`: it is reachable only from qkd-net and mgmt-net, and on the
public host from qkd-net only (the cloud overlay takes the KMEs off mgmt-net,
where Caddy and the frontend sit). Four things keep it there, and each is
checked:

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
        for name in KME_SERVICES & set(services):
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


# ---- the public overlay keeps the KMEs off the internet-facing network -------
# mgmt-net is where Caddy and the frontend sit, and where a caddy.d/ drop-in on
# the public host attaches the containers of the other sites Caddy serves. The
# overlay takes the KMEs and pqc-validator off it, so none of those can reach
# the unauthenticated key API; the nodes, webui-backend and pqc-validator
# reach the KMEs on qkd-net, which is internal.

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
    facing = nets["caddy"] | nets["webui-frontend"]
    assert facing, "found no networks for Caddy or the frontend"
    for name in sorted(KME_SERVICES | {"pqc-validator"}):
        shared = nets[name] & facing
        assert not shared, f"{name} shares {sorted(shared)} with Caddy or the frontend on the public host"
    # What must still connect does.
    assert nets["webui-backend"] & nets["bb84-kme-a"], "webui-backend cannot reach the KMEs"
    assert nets["webui-backend"] & nets["pqc-validator"], "webui-backend cannot reach pqc-validator"
    assert nets["webui-backend"] & nets["webui-frontend"], "the frontend cannot reach webui-backend"
    assert nets["alice"] & nets["bb84-kme-a"], "the WireGuard nodes cannot reach the KMEs"


def test_the_override_check_sees_a_merge_as_a_merge():
    # Without `!override` Compose merges the overlay's networks into the base
    # ones, and the KME would stay on mgmt-net; the check must model that.
    doc = yaml.load("networks:\n  qkd-net: {}\n", Loader=_OverrideLoader)
    assert not isinstance(doc["networks"], _Override)
    doc = yaml.load("networks: !override\n  qkd-net: {}\n", Loader=_OverrideLoader)
    assert isinstance(doc["networks"], _Override)
