"""Live KME overrides are opt-in: off unless ENABLE_LIVE_PARAM_OVERRIDES is set.

POST /api/sim/backend, /api/sim/params and /api/sim/params/reset write to state
that is process-global on BOTH KMEs -- the simulator backend and one in-memory
override set, `eve.enabled` and `protocol.qber_threshold_abort` included. Those
KMEs fill the key pool arnika draws the QKD half of every PSK from, on both live
VPN lanes. On the public demo any anonymous visitor could set them, and every
other visitor and both lanes then ran on that visitor's choice: last write wins.

The fix follows ENABLE_CONTAINER_CONTROL: opt-in, parsed the same way, so a
missing or misspelled variable yields the safe deployment. The contract other
parts of the repository rely on, pinned here:

  * flag off -> each of the three routes is 403 with one exact detail string,
    and no request leaves the backend;
  * the GET routes are unchanged;
  * GET /api/config reports the flag as `live_param_overrides`.
"""
from __future__ import annotations

import importlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest
from conftest import load_service_app
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
load_service_app("webui-backend", "webui_backend_app")
main = importlib.import_module("webui_backend_app.main")

DETAIL = (
    "live parameter overrides are disabled on this host "
    "(ENABLE_LIVE_PARAM_OVERRIDES=false); edits apply to the in-browser model only"
)
MUTATORS = [
    ("/api/sim/params", {"patch": {"physical.link_length_km": 300}}),
    ("/api/sim/params/reset", None),
    ("/api/sim/backend", {"name": "qkdnetsim_proxy"}),
]


class _Resp:
    def __init__(self, status: int = 200, body=None):
        self.status_code = status
        self._body = body if body is not None else {"ok": True}
        self.text = json.dumps(self._body)

    def json(self):
        return self._body


class _RecordingClient:
    """Stands in for httpx.AsyncClient; every outbound request is recorded."""

    def __init__(self):
        self.calls: list[tuple[str, str]] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def aclose(self):
        """The app's lifespan closes its shared client on shutdown."""

    async def post(self, url, json=None):
        self.calls.append(("POST", url))
        return _Resp()

    async def get(self, url, **kw):
        self.calls.append(("GET", url))
        return _Resp(body={"fields": [], "overrides": {}})


@pytest.fixture
def outbound(monkeypatch):
    client = _RecordingClient()
    monkeypatch.setattr(main.httpx, "AsyncClient", lambda *a, **k: client)
    monkeypatch.setattr(main, "_pure_cache", {})
    return client


def _post(client: TestClient, path: str, body):
    return client.post(path, json=body) if body is not None else client.post(path)


@pytest.mark.parametrize("path,body", MUTATORS)
def test_each_mutator_is_403_when_the_flag_is_off(monkeypatch, outbound, path, body):
    monkeypatch.setattr(main, "LIVE_PARAM_OVERRIDES_ENABLED", False)
    with TestClient(main.app) as client:
        r = _post(client, path, body)
    assert r.status_code == 403, f"{path} answered {r.status_code} with the flag off"
    assert r.json()["detail"] == DETAIL
    assert outbound.calls == [], (
        f"{path} reached a KME with the flag off: {outbound.calls}")


@pytest.mark.parametrize("path", [path for path, _ in MUTATORS])
@pytest.mark.parametrize("body", [None, [1, 2, 3]], ids=["no-body", "wrong-shape"])
def test_a_bodyless_or_misshapen_post_is_403_not_422(monkeypatch, outbound, path, body):
    """The gate runs before body validation, so the refusal names the switch.

    With the check inside the handler, both of these reached FastAPI's
    validator first and came back 422 on the two routes that take a body. (A
    body that is not JSON at all is still 422: the parser runs before any
    dependency.)
    """
    monkeypatch.setattr(main, "LIVE_PARAM_OVERRIDES_ENABLED", False)
    with TestClient(main.app) as client:
        r = _post(client, path, body)
    assert r.status_code == 403, f"{path} answered {r.status_code}: {r.text}"
    assert r.json()["detail"] == DETAIL
    assert outbound.calls == []


@pytest.mark.parametrize("path,body", MUTATORS)
def test_each_mutator_reaches_both_kmes_when_the_flag_is_on(
        monkeypatch, outbound, path, body):
    monkeypatch.setattr(main, "LIVE_PARAM_OVERRIDES_ENABLED", True)
    with TestClient(main.app) as client:
        r = _post(client, path, body)
    assert r.status_code == 200, r.text
    urls = [u for _, u in outbound.calls]
    assert any(u.startswith(main.KME_A_URL) for u in urls)
    assert any(u.startswith(main.KME_B_URL) for u in urls)


@pytest.mark.parametrize("path", ["/api/sim/params", "/api/sim/params/editable"])
def test_the_get_routes_are_unchanged(monkeypatch, outbound, path):
    monkeypatch.setattr(main, "LIVE_PARAM_OVERRIDES_ENABLED", False)
    with TestClient(main.app) as client:
        r = client.get(path)
    assert r.status_code == 200
    assert outbound.calls == [("GET", f"{main.KME_A_URL}{path.removeprefix('/api')}")]


@pytest.mark.parametrize("flag", [False, True])
def test_api_config_reports_the_flag(monkeypatch, flag):
    monkeypatch.setattr(main, "LIVE_PARAM_OVERRIDES_ENABLED", flag)
    with TestClient(main.app) as client:
        cfg = client.get("/api/config").json()
    assert cfg["live_param_overrides"] is flag


def _flag_in_a_fresh_process(env_value: str | None) -> bool:
    """Import the module in a clean interpreter, as a deployment would."""
    env = {k: v for k, v in os.environ.items() if k != "ENABLE_LIVE_PARAM_OVERRIDES"}
    env["LOG_DIR"] = tempfile.mkdtemp(prefix="pqcqkd-test-logs-")
    if env_value is not None:
        env["ENABLE_LIVE_PARAM_OVERRIDES"] = env_value
    code = (
        "import importlib.util, sys\n"
        f"pkg = {str(ROOT / 'services/webui-backend/app')!r}\n"
        "spec = importlib.util.spec_from_file_location('wb', pkg + '/__init__.py',"
        " submodule_search_locations=[pkg])\n"
        "m = importlib.util.module_from_spec(spec); sys.modules['wb'] = m\n"
        "spec.loader.exec_module(m)\n"
        "import importlib; main = importlib.import_module('wb.main')\n"
        "print(main.LIVE_PARAM_OVERRIDES_ENABLED)\n"
    )
    out = subprocess.run([sys.executable, "-c", code], env=env,
                         capture_output=True, text=True, check=True)
    return out.stdout.strip().splitlines()[-1] == "True"


@pytest.mark.parametrize("value,expected", [
    (None, False),        # unset: the safe deployment
    ("", False),
    ("false", False),
    ("0", False),
    ("ture", False),      # misspelled: still safe
    ("true", True),
    ("1", True),
    ("yes", True),
    ("on", True),
])
def test_the_default_is_off_and_parsing_matches_container_control(value, expected):
    assert _flag_in_a_fresh_process(value) is expected
    # Same parser as ENABLE_CONTAINER_CONTROL, so the two flags cannot disagree
    # about what "true" means.
    assert main._truthy(value) is expected
