"""The ETSI GS QKD 004 endpoint stays on the internal networks, and off by default.

The binding has no authentication, like ETSI GS QKD 014 on this stack and
`/internal/sync`: it is reachable only from qkd-net and mgmt-net. Four things
keep it there, and each is checked:

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
