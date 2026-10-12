"""stack-status, the one holder of the Docker socket, serves a fixed GET-only API and nothing else.

Whoever can connect to the Docker socket can start a privileged container with
the host's filesystem mounted, so the service that holds it must not offer
anything the backend does not need: no other method, no other path, no name
outside its tables, no parameter it does not bound, no command it was not
built with, and no call that changes a container. Pinned here:

  1. one table: the image copies webui-backend's stack_contract.py into the
     package under the same name, and the tree holds no second copy;
  2. GET only: every other method is 405 on every path, over real HTTP;
  3. names: a name outside a route's table is 404 before Docker is asked;
  4. parameters: missing, repeated, unknown, non-decimal and out-of-range
     values are 422 before Docker is asked; the contract's bounds are
     inclusive;
  5. commands: the only execs are the contract's strings, in the named node;
  6. no control: across every route, the only Docker calls are lookups, log
     reads, those execs and a ping;
  7. redaction: log text and `wg show` output leave it redacted;
  8. failures: a Docker failure is reported in the reply body, not as an HTTP
     error, and /health is 503 while the daemon does not answer.

The fake Docker client records every call, and any attribute it does not
define -- containers.run, a container's stop() -- is recorded as forbidden and
raises.
"""
from __future__ import annotations

import http.client
import json
import re
import subprocess
import threading
import time
from pathlib import Path

import pytest
from conftest import STACK_CONTRACT, load_stack_status_main

docker = pytest.importorskip("docker")
status = load_stack_status_main()
contract = status.contract

ROOT = Path(__file__).resolve().parents[1]
DOCKERFILE = ROOT / "services" / "stack-status" / "Dockerfile"
SRC = (ROOT / "services" / "stack-status" / "app" / "main.py").read_text(encoding="utf-8")

# Placeholder key, real shape: 43 base64 characters + '='.
_PSK = "PSKpskKEYplaceholder00000000000000000000000="
_PRIV = "PRIVpvtKEYplaceholder0000000000000000000000="
BANNER = f"Arnika PSK:               {_PSK}\nordinary line\n"
WG_DUMP = f"{_PRIV}\tPUB\t51820\toff\nPEER\t{_PSK}\t10.30.0.11:51821\t10.0.0.2/32\t1\t2\t3\t25\n"
WG_SHOW_UNREDACTED = f"interface: wg0\n  private key: {_PRIV}\n\npeer: PEER\n  preshared key: {_PSK}\n"


class _Forbidden:
    """Records an attribute the fakes do not define, then raises for it."""

    def __init__(self, calls: list, owner: str):
        self._calls, self._owner = calls, owner

    def __getattr__(self, attr):
        if attr.startswith("_"):
            raise AttributeError(attr)
        self._calls.append(("FORBIDDEN", self._owner, attr))
        raise AttributeError(f"{self._owner}.{attr} is not something stack-status may call")


class _Container(_Forbidden):
    def __init__(self, name, calls, log, answers):
        super().__init__(calls, name)
        self.name, self._log, self._answers = name, log, answers
        self.status = "running"
        self.attrs = {"State": {"StartedAt": "2026-10-12T00:00:00Z"}}
        self.image = type("Image", (), {"tags": [f"pqcqkd/{name}:local"]})()

    def logs(self, **kw):
        self._calls.append(("logs", self.name, kw))
        return self._log

    def exec_run(self, cmd):
        self._calls.append(("exec_run", self.name, cmd))
        answer = self._answers.get(cmd, (0, b""))
        if isinstance(answer, Exception):
            raise answer
        return answer


class _Docker(_Forbidden):
    def __init__(self, log: bytes = b"", answers: dict | None = None, missing=()):
        calls: list = []
        super().__init__(calls, "client")
        self.calls = calls
        outer = self

        class _Containers(_Forbidden):
            def get(self, name):
                outer.calls.append(("get", name, None))
                if name in missing:
                    raise docker.errors.NotFound(f"No such container: {name}")
                return _Container(name, outer.calls, log, answers or {})

        self.containers = _Containers(calls, "containers")

    def ping(self):
        self.calls.append(("ping", None, None))
        return True


def _api(fake):
    return status.StackStatus(lambda: fake)


def _get(fake, target: str):
    code, body, _ = _api(fake).handle("GET", target)
    return code, body


# The six paths, filled in with a name each route serves.
VALID = [
    contract.PATH_HEALTH,
    contract.PATH_STACK,
    contract.PATH_LOGS.format(name="alice") + "?tail=5",
    contract.PATH_LOG_WINDOW.format(name="alice-ipsec") + "?seconds=60",
    contract.PATH_WG.format(node="alice"),
    contract.PATH_IPSEC.format(node="bob-ipsec"),
]


# ---- 1. one table ---------------------------------------------------------
def test_the_image_copies_the_backends_contract_into_the_package():
    text = DOCKERFILE.read_text(encoding="utf-8")
    assert "COPY services/stack-status/app/ ./app/" in text
    assert "COPY services/webui-backend/app/stack_contract.py ./app/stack_contract.py" in text
    assert re.search(r"^RUN python -c \"from app import main", text, re.M), (
        "the build no longer imports the server, so a missing contract would "
        "fail at the first request instead of the build")


def test_the_tree_holds_one_contract():
    tracked = subprocess.run(["git", "ls-files", "*stack_contract.py"], cwd=ROOT,
                             capture_output=True, text=True, check=True).stdout.split()
    # The file this test runs against may not be committed yet; the working
    # tree is checked as well, so a second copy cannot hide by being new.
    present = [str(p.relative_to(ROOT)) for p in (ROOT / "services").rglob("stack_contract.py")
               if "node_modules" not in p.parts]
    assert set(tracked) <= {"services/webui-backend/app/stack_contract.py"}, tracked
    assert present == ["services/webui-backend/app/stack_contract.py"], present


def test_the_service_reads_that_file():
    assert Path(contract.__file__).resolve() == STACK_CONTRACT.resolve()
    assert "from . import stack_contract as contract" in SRC


def test_the_contract_needs_nothing_but_the_standard_library():
    """Two images with different dependencies import it."""
    src = STACK_CONTRACT.read_text(encoding="utf-8")
    imports = re.findall(r"^(?:from|import) (\S+)", src, re.M)
    assert set(imports) <= {"__future__", "re"}, imports


# ---- 2. GET only, over real HTTP ------------------------------------------
@pytest.fixture
def server():
    fake = _Docker(log=b"ordinary line\n")
    srv = status.Server(("127.0.0.1", 0), _api(fake))
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        yield srv.server_address[1], fake
    finally:
        srv.shutdown()
        srv.server_close()


def _request(port: int, method: str, target: str):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        conn.request(method, target, body=b"{}" if method in ("POST", "PUT", "PATCH") else None)
        r = conn.getresponse()
        return r.status, dict(r.getheaders()), r.read()
    finally:
        conn.close()


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE", "OPTIONS", "TRACE", "HEAD"])
@pytest.mark.parametrize("target", [VALID[1], VALID[2], VALID[4], "/v1/exec", "/"])
def test_every_method_but_get_is_405_before_docker(server, method, target):
    port, fake = server
    code, headers, body = _request(port, method, target)
    assert code == 405, f"{method} {target} answered {code}"
    assert headers.get("Allow") == "GET"
    if method == "HEAD":
        assert body == b""
    else:
        assert "GET only" in json.loads(body)["detail"]
    assert fake.calls == [], f"{method} {target} reached Docker: {fake.calls}"


def test_get_is_served_over_http(server):
    port, fake = server
    code, headers, body = _request(port, "GET", VALID[2])
    assert code == 200
    assert headers.get("Content-Type") == "application/json"
    assert json.loads(body)["log"] == "ordinary line\n"
    assert headers.get("Cache-Control") == "no-store"


# ---- 3. paths and names ----------------------------------------------------
@pytest.mark.parametrize("target", [
    "/", "/v1", "/v1/", "/v1/stack/", "//v1/stack", "/V1/stack", "/v1/exec",
    "/v1/containers/alice/exec", "/v1/logs", "/v1/logs/alice/extra?tail=1",
    "/v1/wg/alice/wg0", "/v1/run/alice", "/v1/stack/restart/alice",
])
def test_any_other_path_is_404(target):
    fake = _Docker()
    code, _ = _get(fake, target)
    assert code == 404, target
    assert fake.calls == []


OUTSIDE = [
    (contract.PATH_LOGS, "?tail=1", contract.LOG_CONTAINERS,
     ["caddy", "webui-frontend", "webui-backend", "stack-status", "pqc-validator",
      "qkdnetsim-kme", "ALICE", "alice%2F..", "alice-ipsec-x"]),
    (contract.PATH_LOG_WINDOW, "?seconds=60", contract.LOG_WINDOW_CONTAINERS,
     ["alice", "bob", "bb84-kme-a", "caddy", "stack-status"]),
    (contract.PATH_WG, "", contract.WG_NODES,
     ["alice-ipsec", "bb84-kme-a", "webui-frontend", "caddy"]),
    (contract.PATH_IPSEC, "", contract.IPSEC_NODES,
     ["alice", "bob", "bb84-kme-b", "caddy"]),
]


@pytest.mark.parametrize("template,query,table,names", OUTSIDE,
                         ids=["logs", "log-window", "wg", "ipsec"])
def test_a_name_outside_the_routes_table_is_404_before_docker(template, query, table, names):
    for name in names:
        assert name not in table, name
        fake = _Docker()
        code, body = _get(fake, template.replace("{name}", name).replace("{node}", name) + query)
        assert code == 404, (template, name)
        assert "unknown container" in body["detail"]
        assert fake.calls == [], (template, name, fake.calls)


@pytest.mark.parametrize("template,query,table,_", OUTSIDE, ids=["logs", "log-window", "wg", "ipsec"])
def test_every_name_in_the_routes_table_is_served(template, query, table, _):
    for name in table:
        fake = _Docker()
        code, body = _get(fake, template.replace("{name}", name).replace("{node}", name) + query)
        assert code == 200, (template, name, body)
        assert body["error"] is None
        assert fake.calls[0] == ("get", name, None)


def test_log_windows_are_served_for_the_rotation_counter_alone():
    """/api/vpn/ppk-rotations counts the IPsec nodes' lines; nothing else reads a window."""
    assert contract.LOG_WINDOW_CONTAINERS == contract.IPSEC_NODES == ("alice-ipsec", "bob-ipsec")


# ---- 4. parameters ---------------------------------------------------------
LOGS = contract.PATH_LOGS.format(name="alice")
WINDOW = contract.PATH_LOG_WINDOW.format(name="alice-ipsec")


@pytest.mark.parametrize("target", [
    LOGS, LOGS + "?tail=", LOGS + "?tail=0", LOGS + f"?tail={contract.LOGS_MAX_TAIL + 1}",
    LOGS + "?tail=-1", LOGS + "?tail=%2B5", LOGS + "?tail=%205", LOGS + "?tail=1e3",
    LOGS + "?tail=5.0", LOGS + "?tail=0x10", LOGS + "?tail=" + "9" * 12,
    LOGS + "?tail=5&tail=6", LOGS + "?tail=5&since=1", LOGS + "?lines=5",
    LOGS + "?tail=1&a=1&b=2&c=3&d=4",
    WINDOW, WINDOW + "?seconds=0", WINDOW + f"?seconds={contract.LOG_WINDOW_MAX_S + 1}",
    WINDOW + "?seconds=60&seconds=60", WINDOW + "?tail=5", WINDOW + "?since=1",
    contract.PATH_STACK + "?all=1", contract.PATH_HEALTH + "?x=1",
    contract.PATH_WG.format(node="alice") + "?cmd=dump",
    contract.PATH_IPSEC.format(node="alice-ipsec") + "?cmd=x",
])
def test_a_parameter_outside_the_api_is_422_before_docker(target):
    fake = _Docker()
    code, body = _get(fake, target)
    assert code == 422, (target, body)
    assert fake.calls == [], (target, fake.calls)


def test_the_bounds_are_the_contracts_and_inclusive():
    for tail in (1, contract.LOGS_MAX_TAIL):
        fake = _Docker()
        assert _get(fake, f"{LOGS}?tail={tail}")[0] == 200
        assert fake.calls[-1] == ("logs", "alice", {"stdout": True, "stderr": True, "tail": tail})
    for seconds in (1, contract.LOG_WINDOW_MAX_S):
        fake = _Docker()
        before = int(time.time())
        code, body = _get(fake, f"{WINDOW}?seconds={seconds}")
        assert code == 200 and body["seconds"] == seconds
        kind, _, kw = fake.calls[-1]
        assert kind == "logs" and set(kw) == {"stdout", "stderr", "since"}
        assert before - seconds <= kw["since"] <= int(time.time()) - seconds


def test_the_backend_and_the_service_share_the_bounds():
    """webui-backend's defaults are the contract's, so a default request is never refused."""
    src = (ROOT / "services" / "webui-backend" / "app" / "main.py").read_text(encoding="utf-8")
    assert 'os.environ.get("LOGS_MAX_TAIL", str(stack_contract.LOGS_MAX_TAIL))' in src
    assert "str(stack_contract.LOG_WINDOW_MAX_S)" in src


# ---- 5. commands -------------------------------------------------------------
@pytest.mark.parametrize("node", contract.WG_NODES)
def test_the_wg_route_runs_the_two_show_commands_and_nothing_else(node):
    fake = _Docker()
    code, body = _get(fake, contract.PATH_WG.format(node=node))
    assert code == 200
    assert fake.calls == [("get", node, None)] + [
        ("exec_run", node, cmd) for cmd in contract.WG_SHOW_CMDS.values()]
    assert set(body["results"]) == set(contract.WG_SHOW_CMDS)
    assert all("dump" not in cmd for cmd in contract.WG_SHOW_CMDS.values())


@pytest.mark.parametrize("node", contract.IPSEC_NODES)
def test_the_ipsec_route_runs_the_two_swanctl_commands_and_nothing_else(node):
    fake = _Docker()
    code, body = _get(fake, contract.PATH_IPSEC.format(node=node))
    assert code == 200
    assert fake.calls == [("get", node, None)] + [
        ("exec_run", node, cmd) for cmd in contract.SWANCTL_CMDS.values()]
    assert set(body["results"]) == set(contract.SWANCTL_CMDS)


def test_the_source_runs_only_the_contracts_commands():
    """One exec_run, over a table, and the tables passed to it are the contract's."""
    assert SRC.count(".exec_run(") == 1
    assert "for label, cmd in commands.items():" in SRC
    calls = re.findall(r"self\._run_fixed\(([^)]*)\)", SRC)
    assert sorted(c.split(",")[1].strip() for c in calls) == [
        "contract.SWANCTL_CMDS", "contract.WG_SHOW_CMDS"], calls


# ---- 6. no control -----------------------------------------------------------
def test_no_route_makes_a_call_that_could_change_anything():
    fake = _Docker(log=b"line\n")
    api = _api(fake)
    for target in VALID:
        code, body, _ = api.handle("GET", target)
        assert code == 200, (target, body)
    forbidden = [c for c in fake.calls if c[0] == "FORBIDDEN"]
    assert forbidden == [], forbidden
    assert {c[0] for c in fake.calls} <= {"get", "logs", "exec_run", "ping"}


def test_the_source_names_no_mutating_docker_call():
    pattern = re.compile(
        r"\.(run|create|start|stop|restart|kill|remove|pause|unpause|update|rename|"
        r"put_archive|exec_create|exec_start|prune|commit|attach|pull|push|build)\(")
    assert not pattern.findall(SRC), pattern.findall(SRC)


# ---- 7. redaction ------------------------------------------------------------
def test_log_text_leaves_redacted_with_its_count():
    fake = _Docker(log=BANNER.encode())
    code, body = _get(fake, f"{LOGS}?tail=10")
    assert code == 200
    assert _PSK not in body["log"]
    assert "ordinary line" in body["log"]
    assert body["redacted"] == 1


def test_a_log_window_leaves_redacted_too():
    fake = _Docker(log=BANNER.encode())
    _, body = _get(fake, f"{WINDOW}?seconds=60")
    assert _PSK not in body["log"]


@pytest.mark.parametrize("output", [WG_DUMP, WG_SHOW_UNREDACTED])
def test_wg_output_leaves_redacted(output):
    answers = {cmd: (0, output.encode()) for cmd in contract.WG_SHOW_CMDS.values()}
    _, body = _get(_Docker(answers=answers), contract.PATH_WG.format(node="alice"))
    for result in body["results"].values():
        assert _PRIV not in result["output"]
        assert _PSK not in result["output"]


# ---- 8. failures -------------------------------------------------------------
def test_a_missing_container_is_an_error_in_the_body():
    code, body = _get(_Docker(missing={"alice"}), f"{LOGS}?tail=1")
    assert code == 200
    assert body["log"] is None and body["redacted"] is None
    assert "No such container" in body["error"]


def test_a_failed_exec_is_reported_for_its_own_command_only():
    answers = {contract.WG_DATA_SHOW_CMD: RuntimeError("exec failed")}
    _, body = _get(_Docker(answers=answers), contract.PATH_WG.format(node="alice"))
    assert body["error"] is None
    assert body["results"]["wg0"]["error"] is None
    assert body["results"]["wg1"] == {"rc": None, "output": None, "error": "exec failed"}


def test_an_error_text_is_bounded():
    long = "z" * (contract.ERROR_TEXT_MAX_CHARS * 3)
    answers = {contract.WG_SHOW_CMD: RuntimeError(long)}
    _, body = _get(_Docker(answers=answers), contract.PATH_WG.format(node="bob"))
    assert body["results"]["wg0"]["error"] == long[:contract.ERROR_TEXT_MAX_CHARS]


def test_a_daemon_that_does_not_answer_is_reported_everywhere():
    def unreachable():
        raise docker.errors.DockerException("Error while fetching server API version")

    api = status.StackStatus(unreachable)
    code, body, _ = api.handle("GET", contract.PATH_HEALTH)
    assert code == 503 and "did not answer" in body["detail"]
    code, body, _ = api.handle("GET", contract.PATH_STACK)
    assert code == 200
    assert {r["status"] for r in body["containers"]} == {"unknown"}
    assert all("server API version" in r["error"] for r in body["containers"])
    code, body, _ = api.handle("GET", f"{LOGS}?tail=1")
    assert code == 200 and "server API version" in body["error"]


def test_the_client_is_created_again_after_a_failure():
    """A daemon that was not up when the service started is used once it is."""
    fake = _Docker()
    attempts = []

    def factory():
        attempts.append(1)
        if len(attempts) == 1:
            raise docker.errors.DockerException("not yet")
        return fake

    api = status.StackStatus(factory)
    assert api.handle("GET", contract.PATH_HEALTH)[0] == 503
    assert api.handle("GET", contract.PATH_HEALTH)[0] == 200
    assert api.handle("GET", contract.PATH_HEALTH)[0] == 200
    assert len(attempts) == 2, "the working client was not kept"


def test_health_is_200_when_the_daemon_answers():
    code, body = _get(_Docker(), contract.PATH_HEALTH)
    assert (code, body) == (200, {"status": "ok"})


def test_a_route_that_raises_is_a_500_with_the_reason():
    """A defect in a route answers, bounded, rather than dropping the connection."""
    api = _api(_Docker())
    api._routes = ((status._pattern(contract.PATH_STACK), lambda raw_query: 1 / 0),)
    code, body, _ = api.handle("GET", contract.PATH_STACK)
    assert code == 500
    assert body == {"detail": "division by zero"}
