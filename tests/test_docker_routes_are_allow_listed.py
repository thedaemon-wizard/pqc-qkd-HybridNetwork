"""The routes that take a container name from the URL reach only named containers.

`GET /api/logs/{name}` called `cli.containers.get(name)` for ANY name. Its only
caller, /console, asks for six. On the public demo (2026-09-25) `/api/logs/caddy`
answered 200 with the reverse proxy's access log -- visitor IPs and User-Agents --
and `/api/logs/webui-frontend` answered 200 too. `GET /api/wg/{node}` ran
`docker exec wg show wg0` in whatever container the path named; nothing in the
frontend calls it at all.

Both now check one table in main.py (LOG_CONTAINERS, and WG_NODES inside it)
and answer 404 for anything else BEFORE Docker is asked. The fake Docker client
below records every lookup, so "404" cannot be satisfied by a real lookup that
happened to fail.
"""
from __future__ import annotations

import importlib
import re
from pathlib import Path

import pytest
from conftest import load_service_app
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
CONSOLE = ROOT / "services" / "webui-frontend" / "src" / "pages" / "Console.tsx"

load_service_app("webui-backend", "webui_backend_app")
main = importlib.import_module("webui_backend_app.main")


class _Container:
    def logs(self, tail):
        return b"ordinary line\n"

    def exec_run(self, cmd):
        return 0, b"interface: wg0\n  private key: (hidden)\n"


class _RecordingDocker:
    def __init__(self):
        self.looked_up: list[str] = []
        outer = self

        class _C:
            def get(self, name):
                outer.looked_up.append(name)
                return _Container()

        self.containers = _C()


@pytest.fixture
def get(monkeypatch):
    monkeypatch.setattr(main, "_pure_cache", {})
    fake = _RecordingDocker()

    def _get(path: str):
        prev = getattr(main.app.state, "docker", None)
        try:
            with TestClient(main.app) as client:
                main.app.state.docker = fake
                return client.get(path)
        finally:
            main.app.state.docker = prev

    _get.docker = fake
    return _get


@pytest.mark.parametrize("name", ["caddy", "webui-frontend", "webui-backend",
                                  "pqc-validator", "qkdnetsim-kme", "does-not-exist"])
def test_logs_of_an_unlisted_container_are_404_without_asking_docker(get, name):
    r = get(f"/api/logs/{name}?tail=1")
    assert r.status_code == 404, f"/api/logs/{name} answered {r.status_code}"
    assert get.docker.looked_up == [], (
        f"/api/logs/{name} reached the Docker socket before being refused")


@pytest.mark.parametrize("name", main.LOG_CONTAINERS)
def test_every_console_container_is_still_served(get, name):
    r = get(f"/api/logs/{name}?tail=1")
    assert r.status_code == 200, r.text
    assert get.docker.looked_up == [name]


@pytest.mark.parametrize("node", ["webui-frontend", "caddy", "bb84-kme-a", "alice-ipsec"])
def test_wg_show_outside_the_wireguard_nodes_is_404_without_exec(get, node):
    r = get(f"/api/wg/{node}")
    assert r.status_code == 404
    assert get.docker.looked_up == []


@pytest.mark.parametrize("node", main.WG_NODES)
def test_wg_show_on_a_wireguard_node_still_works(get, node):
    r = get(f"/api/wg/{node}")
    assert r.status_code == 200
    assert r.json()["node"] == node


def test_one_table_serves_both_routes():
    """WG_NODES is a subset of LOG_CONTAINERS, so the two cannot drift apart."""
    assert set(main.WG_NODES) <= set(main.LOG_CONTAINERS)
    assert set(main.WG_NODES) == {"alice", "bob"}


def test_the_allow_list_is_what_the_console_asks_for():
    """The table is Console.tsx's NAMES, not a guess at them.

    If /console gains a pane, this fails until the backend is told, instead of
    the new pane showing a 404 nobody connects to the allow-list.
    """
    src = CONSOLE.read_text(encoding="utf-8")
    m = re.search(r"const NAMES = \[(.*?)\];", src, re.S)
    assert m, "Console.tsx no longer declares NAMES; re-point this guard"
    names = re.findall(r'"([^"]+)"', m.group(1))
    assert tuple(names) == main.LOG_CONTAINERS


def test_expired_log_entries_do_not_accumulate(get):
    """The cache is keyed per (name, tail); a sweep over `tail` must not leave
    thousands of stale log bodies in memory for the life of the process."""
    for tail in (1, 2, 3):
        assert get(f"/api/logs/alice?tail={tail}").status_code == 200
    # Age those three past the TTL by rewriting their timestamps, rather than
    # freezing the clock the test client itself runs on.
    for k, v in main._pure_cache.items():
        if k.startswith("logs:"):
            v["at"] -= main.LOGS_TTL_S + 1
    assert get("/api/logs/alice?tail=4").status_code == 200
    keys = [k for k in main._pure_cache if k.startswith("logs:")]
    assert keys == ["logs:alice:4"], keys
