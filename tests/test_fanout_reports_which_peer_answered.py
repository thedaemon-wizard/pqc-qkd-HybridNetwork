"""Three control endpoints returned `{"ok": true}` when neither KME answered.

`/api/sim/backend`, `/api/sim/params` and `/api/sim/params/reset` each POST to
BOTH KMEs. Each wrapped the call in `try/except Exception` that logged and
continued, then returned `{"ok": True}` unconditionally. With both peers down
the caller got HTTP 200 and `{"ok": true}`, and `/physics` printed

    "Reverted to config/qkd_params.yaml defaults."

having changed nothing anywhere. The log line the backend wrote is not
something the operator sees.

Same family as the Overview restart button that always 403'd: an action
reporting success it does not have. There the promise was discarded by the
caller; here the success was fabricated one layer earlier, which is worse --
no amount of care at the call site could have recovered it.

The half-applied case is the one worth naming. These two KMEs must agree on the
physics; if alice takes an override and bob does not, the key rates they report
diverge for a reason nothing surfaces. `{"ok": true}` covered that state too.

`ok` now means every peer was reached AND answered non-4xx/5xx. `nodes` says
which, so half-applied is visible. A 4xx still raises, because a rejected
override is a validation error the user must see rather than a peer being down.

The backend switch goes further and answers with an HTTP error unless BOTH KMEs
applied it: the refusing KME's status, or 502 for one that could not be
reached. It used to wrap a KME's 400 or 503 in HTTP 200, so /physics printed
"Backend switch to qkdnetsim_proxy requested." while both KMEs had refused it.
The parameter routes keep reporting an unreachable peer in-band (`ok: false`).

All three routes are opt-in (ENABLE_LIVE_PARAM_OVERRIDES); these tests turn
the flag on, and tests/test_live_param_overrides_are_opt_in.py covers it off.
"""

from __future__ import annotations

import importlib

import pytest
from conftest import load_service_app

load_service_app("webui-backend", "webui_backend_app")
main = importlib.import_module("webui_backend_app.main")


class _Resp:
    def __init__(self, status: int, body=None, text: str = ""):
        self.status_code = status
        self._body = body if body is not None else {}
        self.text = text

    def json(self):
        return self._body


class _Client:
    """Stands in for httpx.AsyncClient, recording every POST it receives."""

    def __init__(self, behaviour):
        self.behaviour = behaviour
        self.calls: list[str] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, json=None):
        self.calls.append(url)
        outcome = self.behaviour(url)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


@pytest.fixture(autouse=True)
def _overrides_enabled(monkeypatch):
    """What these tests exercise is the fan-out, on a host that opted in."""
    monkeypatch.setattr(main, "LIVE_PARAM_OVERRIDES_ENABLED", True)


def _run(coro):
    import asyncio
    return asyncio.run(coro)


def _patch(monkeypatch, behaviour) -> _Client:
    client = _Client(behaviour)
    monkeypatch.setattr(main.httpx, "AsyncClient", lambda *a, **k: client)
    return client


ALL_DOWN = lambda url: ConnectionError("connection refused")          # noqa: E731
ALL_UP = lambda url: _Resp(200, {"applied": True})                     # noqa: E731


def _only_alice_up(url):
    return _Resp(200, {"applied": True}) if main.KME_A_URL in url \
        else ConnectionError("connection refused")


def test_neither_peer_reachable_is_not_ok(monkeypatch):
    """The case that used to return {"ok": true} with HTTP 200."""
    _patch(monkeypatch, ALL_DOWN)
    out = _run(main.sim_params_reset_proxy())

    assert out["ok"] is False, (
        "/api/sim/params/reset reported success with neither KME reachable. "
        "The page then tells the operator the change was applied."
    )
    assert out["reached"] == 0 and out["of"] == 2
    for node in ("alice", "bob"):
        assert out["nodes"][node]["ok"] is False
        assert out["nodes"][node]["error"]


@pytest.mark.parametrize("endpoint", ["backend", "reset"])
def test_both_reachable_is_ok(monkeypatch, endpoint):
    """The other direction -- 'always false' is the same defect inverted."""
    _patch(monkeypatch, ALL_UP)
    call = (main.sim_backend_proxy({"name": "qutip"}) if endpoint == "backend"
            else main.sim_params_reset_proxy())
    out = _run(call)
    assert out["ok"] is True
    assert out["reached"] == 2


def test_half_applied_is_visible(monkeypatch):
    """alice took it, bob did not. Previously indistinguishable from success.

    This is the state that matters: the two KMEs must agree on the physics, and
    a silent divergence shows up later as key rates that differ for no visible
    reason.
    """
    _patch(monkeypatch, _only_alice_up)
    out = _run(main.sim_params_reset_proxy())
    assert out["ok"] is False
    assert out["reached"] == 1 and out["of"] == 2
    assert out["nodes"]["alice"]["ok"] is True
    assert out["nodes"]["bob"]["ok"] is False


@pytest.mark.parametrize("behaviour,reachable", [(ALL_DOWN, 0), (_only_alice_up, 1)])
def test_a_backend_switch_that_missed_a_peer_is_an_http_error(
        monkeypatch, behaviour, reachable):
    """A switch that reached one KME leaves the two on different backends;
    that is not a 200 with a flag inside it."""
    from fastapi import HTTPException

    _patch(monkeypatch, behaviour)
    with pytest.raises(HTTPException) as e:
        _run(main.sim_backend_proxy({"name": "qutip"}))
    assert e.value.status_code == 502
    assert "bob: unreachable" in e.value.detail
    assert ("alice: applied" in e.value.detail) is (reachable == 1)


def test_params_applies_the_override_exactly_once(monkeypatch):
    """Guards a bug introduced while fixing this one.

    A first draft read the applied values by POSTing a SECOND time to whichever
    peer had answered -- applying the override twice. The body is now captured
    from the response already received.
    """
    client = _patch(monkeypatch, ALL_UP)
    out = _run(main.sim_params_set_proxy({"physical.link_length_km": 25}))
    assert out["ok"] is True
    assert len(client.calls) == 2, (
        f"posted {len(client.calls)} times to 2 peers: {client.calls}"
    )
    assert out["kme"] == {"applied": True}


def test_a_rejected_override_still_raises(monkeypatch):
    """A 4xx is a validation error the user must see, not a peer being down."""
    from fastapi import HTTPException

    _patch(monkeypatch, lambda url: _Resp(422, text="link_length_km must be > 0"))
    with pytest.raises(HTTPException) as e:
        _run(main.sim_params_set_proxy({"physical.link_length_km": -1}))
    assert e.value.status_code == 422
    assert "link_length_km" in str(e.value.detail)


def test_the_response_does_not_echo_whole_bodies(monkeypatch):
    """`nodes` answers "did this peer apply it", not "what did it say"."""
    _patch(monkeypatch, ALL_UP)
    out = _run(main.sim_params_set_proxy({"physical.link_length_km": 25}))
    for node in out["nodes"].values():
        assert "body" not in node, "per-node entries leak the full response body"
    assert out["kme"] is not None, "the applied values are still returned, once"


@pytest.mark.parametrize("status", [400, 503])
def test_a_refused_backend_switch_is_an_http_error(monkeypatch, status):
    """A KME that says no must not be reported as a switch requested.

    503 is what bb84-kme answers when the backend's dependency (qkdnetsim-kme)
    is not deployed on the host; 400 is an unknown backend name.
    """
    from fastapi import HTTPException

    _patch(monkeypatch, lambda url: _Resp(status, text="qkdnetsim-kme is not deployed"))
    with pytest.raises(HTTPException) as e:
        _run(main.sim_backend_proxy({"name": "qkdnetsim_proxy"}))
    assert e.value.status_code == status
    assert "alice" in e.value.detail and "bob" in e.value.detail
    assert "not deployed" in e.value.detail
    assert isinstance(e.value.detail, str), (
        "the frontend renders body.detail into a sentence; a dict prints as "
        "[object Object]")


def test_a_half_refused_backend_switch_names_the_peer_that_took_it(monkeypatch):
    from fastapi import HTTPException

    _patch(monkeypatch, lambda url: _Resp(200, {"ok": True}) if main.KME_A_URL in url
           else _Resp(503, text="not deployed"))
    with pytest.raises(HTTPException) as e:
        _run(main.sim_backend_proxy({"name": "qkdnetsim_proxy"}))
    assert e.value.status_code == 503
    assert "alice: applied" in e.value.detail
    assert "bob: HTTP 503" in e.value.detail
