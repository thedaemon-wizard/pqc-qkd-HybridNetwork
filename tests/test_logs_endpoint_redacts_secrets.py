"""`GET /api/logs/{name}` must never emit key material, and must be bounded.

It emitted ARNIKA_PSK. The pinned arnika (3a8cc13) prints its whole
configuration at startup, `Arnika PSK:` line included, with the value verbatim
(submodules/arnika/config/config.go:78). The route was unauthenticated, had no
tail cap and passed container stdout through unchanged, so on the public demo a
large enough `?tail=` reached back past the 129,319 lines alice had logged to the
banner. Measured 2026-09-25 by the LENGTH of the value only -- 44 characters, a
base64 32-byte key -- never by printing it.

Upstream replaced the print with redactSecret() on arnika PR #51, which the pin
now includes, so the banner reaches this project already redacted -- unless a
node is rolled back. This project's redactor is stack_contract.redact_log,
applied twice: by stack-status, which reads the log from Docker, and by
webui-backend on the way out. This file pins five separate things, because
fixing one leaves the others free to drift back:

  1. the arnika banner line is redacted whatever its value looks like;
  2. other key-shaped values after a key-ish label are redacted, while ordinary
     error text after "PSK:" stays readable (the length floor);
  3. the route actually applies the redactor (the wg route shipped a working
     redactor that the handler did not call) -- the backend's own pass too,
     not only stack-status's;
  4. two passes count a withheld value once, so `redacted` says what it always
     said;
  5. `tail` / `lines` are bounded, and both handlers are plain `def` so the
     blocking call runs in the threadpool, not on the event loop.

Placeholders have real key shapes so a length-based check cannot pass on a
shorter stand-in.
"""
from __future__ import annotations

import importlib
import inspect

import httpx
import pytest
from conftest import load_service_app, stack_status_client, stack_status_replying
from fastapi.testclient import TestClient

load_service_app("webui-backend", "webui_backend_app")
_main = importlib.import_module("webui_backend_app.main")

# Real shape: 43 base64 characters + '=' (a 32-byte key), as arnika prints it.
_PSK = "PSKpskKEYplaceholder00000000000000000000000="
_SHORT_PSK = "changeme"

BANNER = f"""\
=== Arnika Configuration ===
Arnika Mode:              QkdAndPqcRequired
Arnika Interval:          30s
Arnika ID:                1
Arnika PSK:               {_PSK}
Arnika Listen Address:    0.0.0.0:9999
KMS URL:                  http://bb84-kme-a:8080
"""

ERROR_LINE = ("2026/09/25 06:48:38 [ERROR] alice failed to configure random PSK: "
              "context deadline exceeded")
ROTATION_LINE = ("2026/09/25 06:48:38 [INFO] alice PSK configured, key_ID "
                 "3f2a9c1e-7b4d-4e2a-9f10-0c5d8e7a6b21")


@pytest.fixture(autouse=True)
def _fresh_cache(monkeypatch):
    """The handlers cache per (name, tail); isolate every test from the others."""
    monkeypatch.setattr(_main, "_pure_cache", {})


# ---- 1. the banner ---------------------------------------------------------
def test_the_arnika_banner_value_is_redacted():
    out, n = _main._redact_log(BANNER)
    assert _PSK not in out
    assert "Arnika PSK:               (redacted)" in out
    assert n == 1


def test_a_short_banner_value_is_redacted_too():
    """A test PSK is still the PSK; the banner rule has no length floor."""
    out, _ = _main._redact_log(f"Arnika PSK: {_SHORT_PSK}\n")
    assert _SHORT_PSK not in out


def test_a_prefixed_banner_line_is_still_caught():
    """Timestamps or ANSI colour ahead of the label must not defeat the rule."""
    out, _ = _main._redact_log(f"\x1b[32m2026/09/25 [INFO]\x1b[0m Arnika PSK: {_PSK}\n")
    assert _PSK not in out


# ---- 2. other key-shaped values, and what must stay readable ------------
@pytest.mark.parametrize("label", ["preshared key", "private key", "PSK", "secret"])
def test_key_shaped_values_after_a_key_label_are_redacted(label):
    out, n = _main._redact_log(f"{label}: {_PSK}\n")
    assert _PSK not in out
    assert n == 1


def test_error_text_after_psk_stays_readable():
    """The 24-character floor is what keeps /console useful for failures."""
    out, n = _main._redact_log(ERROR_LINE)
    assert out == ERROR_LINE
    assert n == 0


def test_a_rotation_line_with_a_key_id_is_left_alone():
    """key_IDs are identifiers, not secrets, and the UUID dashes keep them short."""
    out, n = _main._redact_log(ROTATION_LINE)
    assert out == ROTATION_LINE
    assert n == 0


def test_the_redactor_is_not_a_no_op_on_the_shipped_banner():
    """Guard the guard: a redactor that never fires would pass the tests above
    that check nothing changed."""
    assert _main._redact_log(BANNER)[0] != BANNER


def test_a_second_pass_changes_nothing_and_counts_nothing():
    """stack-status redacts, and the backend redacts again: the second pass must
    neither alter the text nor count the banner a second time."""
    once, n = _main._redact_log(BANNER + f"secret: {_PSK}\n")
    assert n == 2
    assert _main._redact_log(once) == (once, 0)


# ---- 3. through the handler ----------------------------------------------
class _FakeContainer:
    def __init__(self, payload: bytes, seen: list):
        self.payload = payload
        self.seen = seen

    def logs(self, tail, **streams):
        assert streams == {"stdout": True, "stderr": True}, (
            "stack-status must ask for both streams: arnika logs to stderr")
        self.seen.append(tail)
        return self.payload


class _FakeDocker:
    def __init__(self, payload: bytes):
        self.seen: list = []
        outer = self

        class _C:
            def get(self, name):
                return _FakeContainer(payload, outer.seen)

        self.containers = _C()


def _get_through(path: str, status_client):
    prev = getattr(_main.app.state, "stack_status", None)
    try:
        with TestClient(_main.app) as client:
            # The lifespan has just set the client from STACK_STATUS_URL.
            _main.app.state.stack_status = status_client
            return client.get(path)
    finally:
        _main.app.state.stack_status = prev


def _get(path: str, payload: bytes):
    """Through both services: stack-status's handler reads the fake Docker."""
    pytest.importorskip("docker")
    fake = _FakeDocker(payload)
    return _get_through(path, stack_status_client(fake)), fake


def test_the_route_returns_redacted_output():
    r, _ = _get("/api/logs/alice", (BANNER + ROTATION_LINE).encode())
    assert r.status_code == 200
    body = r.json()
    assert _PSK not in body["log"], "the route emitted ARNIKA_PSK"
    assert body["redacted"] == 1, (
        "the route must say that something was withheld, and say it once: "
        "stack-status's pass and the backend's are one withheld value")
    assert "key_ID" in body["log"], "redaction must not swallow ordinary lines"


def test_the_backend_redacts_what_stack_status_did_not():
    """The backend's own pass, tested alone: a stack-status that relayed the
    banner unredacted must still not get it out of this route."""
    def reply(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"name": "alice", "log": BANNER + ROTATION_LINE,
                                         "redacted": 0, "error": None})

    r = _get_through("/api/logs/alice", stack_status_replying(reply))
    assert r.status_code == 200
    assert _PSK not in r.json()["log"], "only stack-status's pass stood between the key and the route"
    assert r.json()["redacted"] == 1


def test_a_container_stack_status_could_not_read_is_404_with_the_reason():
    def reply(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"name": "alice", "log": None, "redacted": None,
                                         "error": "404 Client Error: No such container: alice"})

    r = _get_through("/api/logs/alice", stack_status_replying(reply))
    assert r.status_code == 404
    assert "No such container" in r.json()["detail"]


def test_without_stack_status_the_route_says_it_is_not_available_here():
    r = _get_through("/api/logs/alice", None)
    assert r.status_code == 503
    assert r.json()["detail"].startswith("container logs are not available on this deployment")
    assert "STACK_STATUS_URL" in r.json()["detail"]


def test_stack_status_not_answering_is_503_not_an_empty_log():
    def reply(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    r = _get_through("/api/logs/alice", stack_status_replying(reply))
    assert r.status_code == 503
    assert "stack-status did not answer" in r.json()["detail"]


@pytest.mark.parametrize("tail", [0, -1])
def test_a_non_positive_tail_is_rejected(tail):
    r, fake = _get(f"/api/logs/alice?tail={tail}", BANNER.encode())
    assert r.status_code == 422
    assert fake.seen == [], "an invalid request must not reach Docker"


def test_a_tail_above_the_cap_is_rejected_not_clamped():
    """Rejected, so a caller is told; a silent clamp would return fewer lines
    than asked for with nothing saying so."""
    r, fake = _get(f"/api/logs/alice?tail={_main.LOGS_MAX_TAIL + 1}", BANNER.encode())
    assert r.status_code == 422
    assert fake.seen == []


def test_the_console_request_is_within_the_cap():
    """/console asks for 400 lines (Console.tsx getLogs(active, 400))."""
    r, fake = _get("/api/logs/alice?tail=400", BANNER.encode())
    assert r.status_code == 200
    assert fake.seen == [400]


# ---- 4. the download route and the handler shape -------------------------
def test_the_download_route_is_bounded_and_redacted(monkeypatch):
    monkeypatch.setattr(_main.logging_setup, "list_log_files",
                        lambda: [{"name": "bb84-kme-a.log"}])
    monkeypatch.setattr(_main.logging_setup, "read_tail",
                        lambda name, lines: f"secret = {_PSK}\nordinary line\n")
    with TestClient(_main.app) as client:
        ok = client.get("/api/logs/download/bb84-kme-a?lines=10")
        too_many = client.get(
            f"/api/logs/download/bb84-kme-a?lines={_main.LOGS_MAX_TAIL + 1}")
    assert ok.status_code == 200
    assert _PSK not in ok.text
    assert "ordinary line" in ok.text
    assert too_many.status_code == 422


@pytest.mark.parametrize("handler", ["logs", "download_log", "stack"])
def test_blocking_handlers_are_plain_functions(handler):
    """`async def` around the blocking Docker SDK stalls the event loop that
    serves every other route; /console polls logs every 1.5 s and / polls stack
    every 3 s. Plain `def` runs in FastAPI's threadpool."""
    assert not inspect.iscoroutinefunction(getattr(_main, handler))
