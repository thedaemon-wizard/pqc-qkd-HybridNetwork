"""Deleting from the shared export gallery is opt-in: off unless ENABLE_SHARED_EXPORT_DELETE is set.

The gallery is one directory for every visitor of a host. `DELETE
/api/exports/{filename}` let any of them delete any file in it, someone else's
export included, with nothing but the per-IP rate limiter between an anonymous
loop and an empty gallery. The store does not need visitors' deletes to stay
bounded: it evicts its oldest files past EXPORT_MAX_FILES and
EXPORT_MAX_TOTAL_BYTES on every save.

The switch follows ENABLE_LIVE_PARAM_OVERRIDES: opt-in, parsed by the same
`_truthy`, so a missing or misspelled variable yields the safe deployment. The
contract the rest of the repository relies on, pinned here:

  * flag off -> the route is 403 with one exact detail string, before the file
    name is read and before anything on disk is touched, whatever the name;
  * flag on -> a delete deletes, and a missing file is 404, as before;
  * GET /api/config reports the flag as `shared_export_delete`;
  * compose forwards the variable with `false` as its default, the example env
    files offer `false`, and the picker's stated reason is the backend's detail
    word for word.
"""
from __future__ import annotations

import base64
import importlib
import os
import pathlib
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest
from conftest import compose_services, load_service_app, read_env_example
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
load_service_app("webui-backend", "webui_backend_app")
main = importlib.import_module("webui_backend_app.main")

DETAIL = (
    "deleting saved exports is disabled on this host "
    "(ENABLE_SHARED_EXPORT_DELETE=false); the gallery is shared by every "
    "visitor and drops its oldest files by itself"
)
PICKER = ROOT / "services" / "webui-frontend" / "src" / "components" / "SavedExportsPicker.tsx"


@pytest.fixture
def store(tmp_path, monkeypatch):
    """A client whose export store is a temporary directory holding one file."""
    monkeypatch.setattr(main, "EXPORT_DIR", str(tmp_path))
    client = TestClient(main.app)
    r = client.post("/api/exports/save", json={
        "name": "chart", "ext": "png",
        "content_b64": base64.b64encode(b"\x89PNG\r\n\x1a\n").decode()})
    assert r.status_code == 200, r.text
    return client, tmp_path, r.json()["filename"]


@pytest.fixture
def unlinks(monkeypatch):
    """Every Path.unlink attempted while the test runs."""
    calls: list[str] = []
    real = pathlib.Path.unlink

    def recording(self, *a, **kw):
        calls.append(str(self))
        return real(self, *a, **kw)

    monkeypatch.setattr(pathlib.Path, "unlink", recording)
    return calls


def test_the_default_detail_is_the_one_the_page_and_the_script_quote():
    assert main.SHARED_EXPORT_DELETE_DISABLED_DETAIL == DETAIL


def test_with_the_flag_off_a_delete_is_403_and_the_file_stays(monkeypatch, store, unlinks):
    monkeypatch.setattr(main, "SHARED_EXPORT_DELETE_ENABLED", False)
    client, tmp_path, name = store
    r = client.delete(f"/api/exports/{name}")
    assert r.status_code == 403, r.text
    assert r.json()["detail"] == DETAIL
    assert [p.name for p in tmp_path.iterdir()] == [name]
    assert unlinks == [], "the refusal reached the filesystem"


@pytest.mark.parametrize("filename", [
    "does-not-exist.png",   # the handler would answer 404
    "x..y",                 # the handler would answer 400 (".." in the name)
    "a%20b",                # the handler would answer 400 (sanitised differently)
])
def test_the_refusal_comes_before_the_name_is_read(monkeypatch, store, unlinks, filename):
    """403 for any name: a 400 or 404 here would mean the handler body ran."""
    monkeypatch.setattr(main, "SHARED_EXPORT_DELETE_ENABLED", False)
    client, _, _ = store
    r = client.delete(f"/api/exports/{filename}")
    assert r.status_code == 403, r.text
    assert r.json()["detail"] == DETAIL
    assert unlinks == []


def test_the_gate_is_a_dependency_of_the_route():
    """Attached to the route, like the live-override gate: not a check inside
    the body that a later edit could move below the filesystem access."""
    route = next(r for r in main.app.routes
                 if getattr(r, "path", None) == "/api/exports/{filename}"
                 and "DELETE" in getattr(r, "methods", ()))
    calls = [d.call for d in route.dependant.dependencies]
    assert main._require_shared_export_delete in calls


def test_with_the_flag_on_a_delete_deletes(monkeypatch, store):
    monkeypatch.setattr(main, "SHARED_EXPORT_DELETE_ENABLED", True)
    client, tmp_path, name = store
    assert client.delete(f"/api/exports/{name}").status_code == 200
    assert list(tmp_path.iterdir()) == []
    assert client.delete(f"/api/exports/{name}").status_code == 404


def test_the_other_export_routes_do_not_depend_on_the_flag(monkeypatch, store):
    monkeypatch.setattr(main, "SHARED_EXPORT_DELETE_ENABLED", False)
    client, _, name = store
    assert client.get("/api/exports/list").json()["exports"][0]["name"] == name
    assert client.get(f"/api/exports/download/{name}").status_code == 200


@pytest.mark.parametrize("flag", [False, True])
def test_api_config_reports_the_flag(monkeypatch, flag):
    monkeypatch.setattr(main, "SHARED_EXPORT_DELETE_ENABLED", flag)
    with TestClient(main.app) as client:
        assert client.get("/api/config").json()["shared_export_delete"] is flag


def _flag_in_a_fresh_process(env_value: str | None) -> bool:
    """Import the module in a clean interpreter, as a deployment would."""
    env = {k: v for k, v in os.environ.items() if k != "ENABLE_SHARED_EXPORT_DELETE"}
    env["LOG_DIR"] = tempfile.mkdtemp(prefix="pqcqkd-test-logs-")
    if env_value is not None:
        env["ENABLE_SHARED_EXPORT_DELETE"] = env_value
    code = (
        "import importlib.util, sys\n"
        f"pkg = {str(ROOT / 'services/webui-backend/app')!r}\n"
        "spec = importlib.util.spec_from_file_location('wb', pkg + '/__init__.py',"
        " submodule_search_locations=[pkg])\n"
        "m = importlib.util.module_from_spec(spec); sys.modules['wb'] = m\n"
        "spec.loader.exec_module(m)\n"
        "import importlib; main = importlib.import_module('wb.main')\n"
        "print(main.SHARED_EXPORT_DELETE_ENABLED)\n"
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
def test_the_default_is_off_and_parsing_matches_the_other_switches(value, expected):
    assert _flag_in_a_fresh_process(value) is expected
    assert main._truthy(value) is expected


def test_compose_forwards_the_variable_with_a_false_default():
    env = compose_services([ROOT / "docker-compose.yml"])["webui-backend"]["env"]
    assert env["ENABLE_SHARED_EXPORT_DELETE"] == "${ENABLE_SHARED_EXPORT_DELETE:-false}"


@pytest.mark.parametrize("example", [".env.example", "deploy/.env.example"])
def test_the_example_env_files_offer_it_off(example):
    assert read_env_example(ROOT / example)["ENABLE_SHARED_EXPORT_DELETE"] == "false"


def test_no_overlay_switches_it_on():
    """The public host's overlays must not turn it on behind .env's back."""
    for overlay in sorted((ROOT / "deploy").glob("docker-compose*.yml")):
        env = compose_services([ROOT / "docker-compose.yml", overlay])["webui-backend"]["env"]
        assert env["ENABLE_SHARED_EXPORT_DELETE"] == "${ENABLE_SHARED_EXPORT_DELETE:-false}", overlay


def test_the_picker_states_the_backend_s_reason_word_for_word():
    """What the page says when it offers no Delete is what the route answers."""
    assert DETAIL in PICKER.read_text(encoding="utf-8")


def test_the_hardening_script_fails_when_deletion_is_on():
    """Read like the rate-limit and live-override checks: the arm that sees the
    flag on, and the arm that sees the route delete, must change the exit code."""
    from test_release_gates_can_actually_fail import _case_branch

    script = (ROOT / "scripts" / "verify-demo-hardening.sh").read_text(encoding="utf-8")
    assert '"shared_export_delete":false' in script
    assert "fail=1" in _case_branch(script, '*\'"shared_export_delete":true\'*')
    probe = script[script.index("-X DELETE"):]
    assert "deleting saved exports is disabled" in probe, (
        "the route probe no longer identifies the refusal by its body")
    assert "fail=1" in _case_branch(probe, "404)"), (
        "a host that deletes (and answered 404 for the absent probe) would pass")
