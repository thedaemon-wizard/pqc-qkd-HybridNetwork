"""`GET /api/logs/{name}` must never emit key material, and must be bounded.

It emitted ARNIKA_PSK. The pinned arnika (3a8cc13) prints its whole
configuration at startup, `Arnika PSK:` line included, with the value verbatim
(submodules/arnika/config/config.go:78). The route was unauthenticated, had no
tail cap and passed container stdout through unchanged, so on the public demo a
large enough `?tail=` reached back past the 129,319 lines alice had logged to the
banner. Measured 2026-09-25 by the LENGTH of the value only -- 44 characters, a
base64 32-byte key -- never by printing it.

Upstream replaced the print with redactSecret() on arnika PR #51. Until the pin
moves past it the backend is the only guard, and this file pins four separate
things, because fixing one leaves the others free to drift back:

  1. the arnika banner line is redacted whatever its value looks like;
  2. other key-shaped values after a key-ish label are redacted, while ordinary
     error text after "PSK:" stays readable (the length floor);
  3. the route actually applies the redactor (the wg route shipped a working
     redactor that the handler did not call);
  4. `tail` / `lines` are bounded, and both handlers are plain `def` so the
     blocking Docker SDK runs in the threadpool, not on the event loop.

Placeholders have real key shapes so a length-based check cannot pass on a
shorter stand-in.
"""
from __future__ import annotations

import importlib
import inspect

import pytest
from conftest import load_service_app
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


# ---- 3. through the handler ----------------------------------------------
class _FakeContainer:
    def __init__(self, payload: bytes, seen: list):
        self.payload = payload
        self.seen = seen

    def logs(self, tail):
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


def _get(path: str, payload: bytes):
    prev = getattr(_main.app.state, "docker", None)
    fake = _FakeDocker(payload)
    try:
        with TestClient(_main.app) as client:
            # TestClient's lifespan re-runs startup, which may reset the client.
            _main.app.state.docker = fake
            r = client.get(path)
    finally:
        _main.app.state.docker = prev
    return r, fake


def test_the_route_returns_redacted_output():
    r, _ = _get("/api/logs/alice", (BANNER + ROTATION_LINE).encode())
    assert r.status_code == 200
    body = r.json()
    assert _PSK not in body["log"], "the route emitted ARNIKA_PSK"
    assert body["redacted"] == 1, "the route must say that something was withheld"
    assert "key_ID" in body["log"], "redaction must not swallow ordinary lines"


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
