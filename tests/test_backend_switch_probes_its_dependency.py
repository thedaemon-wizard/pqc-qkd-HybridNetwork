"""A live backend switch is refused when the backend cannot run on this host.

/physics offered `qkdnetsim_proxy` and `composite_sim_to_net` as live buttons.
Both pull keys from the `qkdnetsim-kme` container, which exists only in the
`crossvalidate` compose overlay and is absent from the default stack by design.
The switch was accepted anyway: `KeyPool.switch_backend` built the backend and
swapped it in without asking whether its dependency was there.

Every round after that failed (`http://qkdnetsim-kme:80` does not resolve) and
was recorded as aborted. The producer loop had no pause after a failed round,
so it spun; the pool stopped refilling; arnika's enc_keys eventually got 503.
And the webui-backend wrapped the KMEs' answers in HTTP 200, so /physics said
"Backend switch to qkdnetsim_proxy requested."

Three things are pinned here:

  1. the candidate backend is preflighted BEFORE it replaces the running one,
     and a failed preflight leaves the running backend untouched;
  2. POST /sim/backend turns that failure into a 503 carrying the reason;
  3. after a round that could not run at all, the producer waits instead of
     retrying at once.
"""
from __future__ import annotations

import asyncio
import importlib
from dataclasses import replace
from pathlib import Path

import httpx
import pytest
from conftest import load_service_app

load_service_app("bb84-kme", "bb84_kme_app")
keypool = importlib.import_module("bb84_kme_app.keypool")
base = importlib.import_module("bb84_kme_app.backends.base")
proxy_mod = importlib.import_module("bb84_kme_app.backends.qkdnetsim_proxy")
composite_mod = importlib.import_module("bb84_kme_app.backends.composite_sim_to_net")
backends = importlib.import_module("bb84_kme_app.backends")

config_loader = importlib.import_module("bb84_kme_app.config_loader")

QKDNETSIM_BACKENDS = ["qkdnetsim_proxy", "qkdnetsim", "composite", "composite_sim_to_net"]


@pytest.fixture(autouse=True)
def _shipped_config(monkeypatch):
    """The backends read config/qkd_params.yaml, as they do in the image."""
    monkeypatch.setattr(config_loader, "CONFIG_PATH",
                        Path(__file__).resolve().parents[1] / "config" / "qkd_params.yaml")
    config_loader.reload()


class _Unreachable:
    """httpx.AsyncClient for a host on which qkdnetsim-kme does not resolve."""

    def __init__(self, *a, **k):
        self.urls: list[str] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, url, **kw):
        raise httpx.ConnectError("[Errno -2] Name or service not known")


class _Healthy(_Unreachable):
    async def get(self, url, **kw):
        return httpx.Response(200, text="ok", request=httpx.Request("GET", url))


class _Idle(base.KeyProducer):
    """The backend that was running before the switch was attempted."""
    backend_name = "idle"

    async def run_round(self):  # pragma: no cover - never driven here
        raise AssertionError("not used")


def _pool() -> keypool.KeyPool:
    pool = keypool.KeyPool.__new__(keypool.KeyPool)
    pool._stats = keypool.PoolStats()
    pool.backend = _Idle(base.cfg_from_yaml())
    pool._backend_name = "idle"
    pool._stats.backend = "idle"
    return pool


@pytest.mark.parametrize("name", QKDNETSIM_BACKENDS)
def test_the_switch_is_refused_when_qkdnetsim_kme_is_not_deployed(monkeypatch, name):
    monkeypatch.setattr(proxy_mod.httpx, "AsyncClient", _Unreachable)
    pool = _pool()
    before = pool.backend
    with pytest.raises(RuntimeError) as e:
        asyncio.run(pool.switch_backend(name))
    assert "not deployed" in str(e.value) and "crossvalidate" in str(e.value)
    assert pool.backend is before, "a refused switch still replaced the backend"
    assert pool._backend_name == "idle"
    assert pool._stats.backend == "idle", "/sim/stats would name a backend that is not running"


@pytest.mark.parametrize("name", QKDNETSIM_BACKENDS)
def test_the_switch_goes_through_when_the_service_answers(monkeypatch, name):
    monkeypatch.setattr(proxy_mod.httpx, "AsyncClient", _Healthy)
    pool = _pool()
    asyncio.run(pool.switch_backend(name))
    assert pool._backend_name == name
    assert pool.backend.backend_name in ("qkdnetsim_proxy", "composite_sim_to_net")


def test_a_non_200_health_is_a_refusal(monkeypatch):
    class _Sick(_Unreachable):
        async def get(self, url, **kw):
            return httpx.Response(503, request=httpx.Request("GET", url))

    monkeypatch.setattr(proxy_mod.httpx, "AsyncClient", _Sick)
    with pytest.raises(RuntimeError, match="HTTP 503"):
        asyncio.run(_pool().switch_backend("qkdnetsim_proxy"))


def test_an_in_process_backend_needs_no_probe():
    """The default preflight is a no-op; only a backend with a remote
    dependency overrides it."""
    asyncio.run(base.KeyProducer.preflight(_Idle(base.cfg_from_yaml())))
    for cls in (proxy_mod.QKDNetSimProxyBackend, composite_mod.CompositeBackend):
        assert cls.preflight is not base.KeyProducer.preflight


def test_the_probe_is_bounded_below_the_fanout_timeout():
    """The webui-backend fan-out gives each KME 5 s; a probe that outlasted it
    would surface as a timeout rather than a 503 with its reason."""
    assert 0 < proxy_mod.HEALTH_PROBE_TIMEOUT_S < 5.0


def test_the_route_maps_a_refusal_to_503(monkeypatch):
    """Checked on the source: importing bb84-kme's main needs the full app."""
    src = (Path(__file__).resolve().parents[1]
           / "services/bb84-kme/app/main.py").read_text(encoding="utf-8")
    i = src.index('@app.post("/sim/backend")')
    body = src[i:src.index("\n@app.", i + 10)]
    assert "await app.state.pool.switch_backend(" in body, (
        "switch_backend is a coroutine now; calling it without await swaps nothing")
    assert "except RuntimeError" in body and "status_code=503" in body


def test_the_producer_waits_after_a_round_that_could_not_run():
    """A spinning producer was the second half of the starvation."""
    rounds = 0

    class _Failing(base.KeyProducer):
        backend_name = "failing"

        async def run_round(self):
            nonlocal rounds
            rounds += 1
            return base.RoundOutcome(
                accepted=False, qber=1.0, key_bytes=b"", n_photons=0, n_sifted=0,
                intercepted=0, elapsed_ms=0.0,
                backend_meta={"backend": "failing", "error": "unreachable"})

    async def drive() -> None:
        pool = keypool.KeyPool.__new__(keypool.KeyPool)
        pool.sae_id = "ALICE"
        pool.peer_kme_url = "http://peer.invalid"
        pool.capacity, pool.low_watermark = 4, 1
        from collections import deque
        pool._buf = deque(maxlen=4)
        pool._by_id, pool._withdrawn = {}, {}
        pool._lock, pool._wake, pool._stopped = asyncio.Lock(), asyncio.Event(), asyncio.Event()
        pool._stats = keypool.PoolStats()
        pool._extra_target, pool._round_ms_total = 0, 0.0
        pool._backend_name = "failing"
        pool.backend = _Failing(replace(base.cfg_from_yaml()))
        task = asyncio.create_task(pool.run())
        await asyncio.sleep(0.2)
        await pool.stop()
        await asyncio.wait_for(task, timeout=5)

    asyncio.run(drive())
    # With the pause, 0.2 s holds one round (the idle poll is seconds). Without
    # it the loop ran thousands.
    assert rounds == 1, f"the producer retried a failing backend {rounds} times in 0.2 s"
