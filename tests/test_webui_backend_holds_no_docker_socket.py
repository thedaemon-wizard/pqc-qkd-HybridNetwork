"""webui-backend holds no Docker socket; stack-status holds it, internally, and alone.

The full profile mounted /var/run/docker.sock into webui-backend, the process
that answers the internet, read-only. A read-only bind mount stops a container
from replacing or unlinking the socket file; it does not make the Docker API
read-only, and whoever can connect can create a privileged container with the
host's filesystem mounted. Container control was off by default, but code
execution in the backend, or in any of its dependencies, was root on the host.

The socket now belongs to stack-status, which serves a fixed GET-only API
(tests/test_stack_status_serves_a_fixed_api.py) on status-net, an internal
network that only webui-backend also joins. Pinned here, for every compose file
and overlay, and for the backend itself:

  * no service but stack-status mounts the socket, in any file or overlay;
  * stack-status publishes no port, is on status-net alone, reads the socket
    read-only, runs read-only with no capability and no privilege gain, and
    has a healthcheck on its own /health;
  * status-net is internal, and its members are webui-backend and stack-status;
  * the backend finds it through STACK_STATUS_URL, on the port it listens on;
    the demo overlay, which starts no stack-status, unsets it, and nothing
    makes the backend depend on it;
  * the backend installs no Docker SDK, imports none, and with no
    stack-status says on every affected route that the data is not available
    on this deployment;
  * container control is refused whatever the environment says;
  * CI installs the service's requirements for these tests and builds its image.
"""
from __future__ import annotations

import importlib
import re
from pathlib import Path

import pytest
import yaml
from conftest import compose_services, load_service_app
from fastapi.testclient import TestClient
from test_compose_env_is_read_by_something import _ComposeLoader

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "docker-compose.yml"
OVERLAYS = sorted(ROOT.glob("docker-compose.*.yml")) + sorted((ROOT / "deploy").glob("docker-compose*.yml"))
ALL_FILES = [BASE] + OVERLAYS
SOCKET = "/var/run/docker.sock"
STATUS_SRC = (ROOT / "services" / "stack-status" / "app" / "main.py").read_text(encoding="utf-8")
LISTEN_PORT = int(re.search(r"^LISTEN_PORT = (\d+)$", STATUS_SRC, re.M).group(1))

load_service_app("webui-backend", "webui_backend_app")
main = importlib.import_module("webui_backend_app.main")


def _doc(path: Path) -> dict:
    return yaml.load(path.read_text(encoding="utf-8"), Loader=_ComposeLoader) or {}


def _sources(service: dict) -> list[str]:
    """The host side of every volume of a service, in either compose syntax."""
    out = []
    for v in service.get("volumes") or []:
        out.append(v.get("source", "") if isinstance(v, dict) else str(v).split(":", 1)[0])
    return out


# ---- the socket ------------------------------------------------------------
@pytest.mark.parametrize("path", ALL_FILES, ids=lambda p: str(p.relative_to(ROOT)))
def test_no_service_but_stack_status_mounts_the_socket(path):
    for name, svc in (_doc(path).get("services") or {}).items():
        if name != "stack-status":
            assert SOCKET not in _sources(svc or {}), f"{path.name}: {name} mounts the Docker socket"


@pytest.mark.parametrize("overlay", OVERLAYS, ids=lambda p: str(p.relative_to(ROOT)))
def test_no_overlay_gives_the_socket_back_to_the_backend(overlay):
    merged = compose_services([BASE, overlay]).get("webui-backend", {}).get("service", {})
    assert SOCKET not in _sources(merged), overlay.name


def test_stack_status_holds_it_read_only_as_a_file():
    svc = _doc(BASE)["services"]["stack-status"]
    mounts = [v for v in svc["volumes"] if str(v).startswith(SOCKET + ":")]
    assert mounts == [f"{SOCKET}:{SOCKET}:ro"], svc["volumes"]


# ---- stack-status's container ---------------------------------------------
def test_stack_status_publishes_no_port_in_any_file():
    for path in ALL_FILES:
        svc = (_doc(path).get("services") or {}).get("stack-status") or {}
        assert not svc.get("ports"), f"{path.name} publishes stack-status"
        assert not svc.get("expose"), f"{path.name} exposes stack-status"


def test_stack_status_is_on_status_net_alone():
    for path in ALL_FILES:
        svc = (_doc(path).get("services") or {}).get("stack-status")
        if svc and "networks" in svc:
            assert set(svc["networks"]) == {"status-net"}, path.name
    assert set(_doc(BASE)["services"]["stack-status"]["networks"]) == {"status-net"}


def test_stack_status_runs_with_nothing_it_does_not_need():
    svc = _doc(BASE)["services"]["stack-status"]
    assert svc.get("read_only") is True
    assert svc.get("cap_drop") == ["ALL"]
    assert "no-new-privileges:true" in (svc.get("security_opt") or [])
    assert "privileged" not in svc and "cap_add" not in svc


def test_stack_status_has_a_healthcheck_on_its_own_health_route():
    test = _doc(BASE)["services"]["stack-status"]["healthcheck"]["test"]
    command = " ".join(test)
    assert f"http://127.0.0.1:{LISTEN_PORT}/health" in command, command
    assert "curl" not in command, "the image carries no curl; the check must not need one"


def test_stack_status_is_built_by_compose_from_the_repository_root():
    """`make build` is `docker compose build`, so a build section is what puts it there."""
    build = _doc(BASE)["services"]["stack-status"]["build"]
    assert build["context"] == "."
    assert (ROOT / build["dockerfile"]).is_file()


def test_the_cloud_overlay_restarts_it_like_every_other_service():
    svc = _doc(ROOT / "deploy" / "docker-compose.cloud.yml")["services"]["stack-status"]
    assert svc.get("restart") == "unless-stopped"


# ---- status-net ------------------------------------------------------------
def test_status_net_is_internal_and_joined_by_the_two_services_alone():
    net = _doc(BASE)["networks"]["status-net"]
    assert net.get("internal") is True
    members = set()
    for path in ALL_FILES:
        for name, svc in (_doc(path).get("services") or {}).items():
            if "status-net" in ((svc or {}).get("networks") or {}):
                members.add(name)
    assert members == {"webui-backend", "stack-status"}, members


# ---- how the backend finds it -----------------------------------------------
def test_the_backend_is_pointed_at_the_port_stack_status_listens_on():
    env = compose_services([BASE])["webui-backend"]["env"]
    assert env["STACK_STATUS_URL"] == f"http://stack-status:{LISTEN_PORT}"


def test_the_demo_overlay_says_there_is_no_stack_status():
    env = compose_services([BASE, ROOT / "deploy" / "docker-compose.demo.yml"])["webui-backend"]["env"]
    assert env["STACK_STATUS_URL"] == ""


def test_the_demo_deploy_does_not_start_stack_status():
    script = (ROOT / "deploy" / "deploy-demo.sh").read_text(encoding="utf-8")
    up = re.search(r"up -d --build ([^\n]+)", script)
    assert up, "deploy-demo.sh no longer names the services it starts"
    services = up.group(1).split()
    assert "webui-backend" in services and "stack-status" not in services, services


def test_nothing_makes_the_backend_start_stack_status():
    """A depends_on would make the demo's `up webui-backend` start the socket holder."""
    for path in ALL_FILES:
        svc = (_doc(path).get("services") or {}).get("webui-backend") or {}
        assert "stack-status" not in (svc.get("depends_on") or {}), path.name


# ---- the backend itself ------------------------------------------------------
def test_the_backend_installs_no_docker_sdk():
    req = (ROOT / "services" / "webui-backend" / "requirements.txt").read_text(encoding="utf-8")
    pins = {re.match(r"[A-Za-z0-9_.-]+", ln.split("#", 1)[0].strip()).group(0).lower()
            for ln in req.splitlines() if ln.split("#", 1)[0].strip()}
    assert "docker" not in pins
    assert "docker" in (ROOT / "services" / "stack-status" / "requirements.txt").read_text()


def test_no_backend_source_imports_it():
    for f in (ROOT / "services" / "webui-backend" / "app").glob("*.py"):
        src = f.read_text(encoding="utf-8")
        assert not re.search(r"^\s*(import docker\b|from docker\b)", src, re.M), f.name
        assert "docker.from_env" not in src and "app.state.docker" not in src, f.name


def test_container_control_is_gone_not_switched_off():
    src = (ROOT / "services" / "webui-backend" / "app" / "main.py").read_text(encoding="utf-8")
    assert "CONTAINER_CONTROL_ENABLED" not in src
    with TestClient(main.app) as client:
        assert client.get("/api/config").json()["container_control"] is False
        for action in ("start", "stop", "restart"):
            r = client.post(f"/api/stack/{action}/alice")
            assert r.status_code == 403
            assert r.json()["detail"] == main.CONTAINER_CONTROL_DISABLED_DETAIL
    # The hardening script identifies the refusal by this prefix.
    assert main.CONTAINER_CONTROL_DISABLED_DETAIL.startswith("container control is disabled")


@pytest.fixture
def no_stack_status(monkeypatch):
    """A deployment without stack-status, as the demo overlay runs."""
    monkeypatch.setattr(main, "STACK_STATUS_URL", "")
    monkeypatch.setattr(main, "_pure_cache", {})
    monkeypatch.setattr(main, "_vpn_sample", {})
    monkeypatch.setattr(main, "_rotation_sample", {})
    with TestClient(main.app) as client:
        assert main.app.state.stack_status is None
        yield client


NOT_HERE = "not available on this deployment"


def test_every_affected_route_says_the_data_is_not_available_here(no_stack_status):
    client = no_stack_status
    rows = client.get("/api/stack").json()
    assert {r["status"] for r in rows} == {"unknown"}
    assert all(NOT_HERE in r["error"] for r in rows), rows[0]
    for path in ("/api/logs/alice?tail=10", "/api/wg/alice", "/api/vpn/protocols"):
        r = client.get(path)
        assert r.status_code == 503, path
        assert NOT_HERE in r.json()["detail"], (path, r.json())
    nodes = client.get("/api/vpn/ppk-rotations").json()["nodes"]
    assert all(NOT_HERE in n["error"] and n["count"] is None for n in nodes.values())


def test_the_names_are_still_checked_first(no_stack_status):
    """A name outside the table is 404 whether or not stack-status exists."""
    assert no_stack_status.get("/api/logs/caddy").status_code == 404
    assert no_stack_status.get("/api/wg/alice-ipsec").status_code == 404


def test_with_the_url_set_the_lifespan_makes_one_client_for_it(monkeypatch):
    monkeypatch.setattr(main, "STACK_STATUS_URL", f"http://stack-status:{LISTEN_PORT}")
    with TestClient(main.app):
        client = main.app.state.stack_status
        assert str(client.base_url).rstrip("/") == f"http://stack-status:{LISTEN_PORT}"
        assert client.timeout.read == main.STACK_STATUS_TIMEOUT_S
        assert client.trust_env is False
    assert client.is_closed, "the lifespan did not close the client it made"


def test_the_backend_waits_longer_than_stack_status_waits_for_docker():
    """So a hung daemon comes back as an `error` in the reply, not as a timeout."""
    docker_timeout = int(re.search(r"^DOCKER_TIMEOUT_S = (\d+)$", STATUS_SRC, re.M).group(1))
    assert main.STACK_STATUS_TIMEOUT_S > docker_timeout


# ---- CI ------------------------------------------------------------------------
def test_ci_installs_the_services_requirements_and_builds_its_image():
    ci = yaml.safe_load((ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8"))
    python = "\n".join(str(s.get("run", "")) for s in ci["jobs"]["python"]["steps"])
    assert "pip install -r services/stack-status/requirements.txt" in python
    images = "\n".join(str(s.get("run", "")) for s in ci["jobs"]["images"]["steps"])
    assert "docker build -f services/stack-status/Dockerfile" in images
