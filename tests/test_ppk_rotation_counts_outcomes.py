"""`/api/vpn/ppk-rotations` counts outcomes, and says when it shortened the window.

Measured on the live demo 2026-09-25 (strongSwan 6.1.0, 8.8 days): 25,249
rotations on each node and 16 failed reauthentications. The endpoint reported
the rotations and nothing else, because arnika-vici logs "PPK rotated" when it
queues the reauthentication, before IKE_AUTH runs. And `?window_s=86400`
answered with `window_s: 3600` and no sign that it had been cut.
"""
from __future__ import annotations

import importlib

import pytest
from conftest import load_service_app
from fastapi.testclient import TestClient

load_service_app("webui-backend", "webui_backend_app")
_main = importlib.import_module("webui_backend_app.main")

LOG = b"""\
2026-09-24T15:15:05Z PPK rotated (id=qkd-bob-23383 len=32)
2026-09-24T15:15:05Z parsed IKE_AUTH response 2 [ N(AUTH_FAILED) ]
2026-09-24T15:15:35Z PPK rotated (id=qkd-bob-23384 len=32)
2026-09-24T15:15:35Z using PPK for PPK_ID 'qkd-bob'
2026-09-24T15:16:05Z PPK rotated (id=qkd-bob-23385 len=32)
2026-09-24T15:16:05Z using PPK for PPK_ID 'qkd-bob'
"""


class _C:
    def logs(self, **_):
        return LOG


class _Docker:
    class containers:
        @staticmethod
        def get(_name):
            return _C()


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(_main, "_rotation_sample", {})
    with TestClient(_main.app) as c:
        prev = _main.app.state.docker
        _main.app.state.docker = _Docker()
        try:
            yield c
        finally:
            _main.app.state.docker = prev


def test_counts_failures_and_applications_not_only_attempts(client):
    body = client.get("/api/vpn/ppk-rotations?window_s=600").json()
    for node in ("alice-ipsec", "bob-ipsec"):
        n = body["nodes"][node]
        assert n["count"] == 3
        assert n["auth_failed"] == 1
        assert n["ppk_applied"] == 2
        # attempts = applied + failed, as on the live demo (25,249 = 25,234 + 16 - 1)
        assert n["count"] == n["ppk_applied"] + n["auth_failed"]
    assert set(body["counts"]) == {"count", "auth_failed", "ppk_applied"}


# The same three rotations as the pinned arnika (f4cf9ba) writes them. It logs
# through log/slog, and the VICI adapter's log.Printf reaches the slog handler
# through the standard library's bridge, so each adapter line arrives as the
# msg="..." value of a key=value record. The counters must not depend on which
# arnika wrote the log: the before/after comparison of the pin reads both.
SLOG_LOG = b"""\
2026-09-26T12:00:05.001Z time=2026-09-26T12:00:05.001Z level=INFO msg="[INFO] [VICI] PPK rotated (id=qkd-bob-23383 ppk_id=ppk-qkd@pqcqkd.local bytes=32)" arnika_id=11
2026-09-26T12:00:05.003Z 07[ENC] parsed IKE_AUTH response 2 [ N(AUTH_FAILED) ]
2026-09-26T12:00:35.001Z time=2026-09-26T12:00:35.001Z level=INFO msg="[INFO] [VICI] PPK rotated (id=qkd-bob-23384 ppk_id=ppk-qkd@pqcqkd.local bytes=32)" arnika_id=11
2026-09-26T12:00:35.002Z 12[CFG] using PPK for PPK_ID 'ppk-qkd@pqcqkd.local'
2026-09-26T12:01:05.001Z time=2026-09-26T12:01:05.001Z level=INFO msg="[INFO] [VICI] PPK rotated (id=qkd-bob-23385 ppk_id=ppk-qkd@pqcqkd.local bytes=32)" arnika_id=11
2026-09-26T12:01:05.002Z 12[CFG] using PPK for PPK_ID 'ppk-qkd@pqcqkd.local'
"""


def test_the_pinned_arnikas_slog_records_count_the_same(client, monkeypatch):
    class Slog:
        def logs(self, **_):
            return SLOG_LOG

    class Docker:
        class containers:
            @staticmethod
            def get(_name):
                return Slog()

    _main.app.state.docker = Docker()
    body = client.get("/api/vpn/ppk-rotations?window_s=600").json()
    for node in ("alice-ipsec", "bob-ipsec"):
        n = body["nodes"][node]
        assert (n["count"], n["distinct_ids"], n["auth_failed"], n["ppk_applied"]) == (3, 3, 1, 2)


def test_a_clamped_window_says_so(client):
    body = client.get("/api/vpn/ppk-rotations?window_s=86400").json()
    assert body["window_s"] == _main.ROTATION_WINDOW_MAX_S
    assert body["requested_window_s"] == 86400
    assert body["capped"] is True
    # And the cached answer for the same window still reports its own request.
    again = client.get("/api/vpn/ppk-rotations?window_s=600").json()
    assert again["requested_window_s"] == 600 and again["capped"] is False


def test_could_not_look_is_not_zero(monkeypatch, client):
    class Broken:
        class containers:
            @staticmethod
            def get(_name):
                raise RuntimeError("no such container")
    _main.app.state.docker = Broken()
    body = client.get("/api/vpn/ppk-rotations?window_s=60").json()
    n = body["nodes"]["alice-ipsec"]
    assert n["auth_failed"] is None and n["ppk_applied"] is None and n["count"] is None
    assert n["error"]
