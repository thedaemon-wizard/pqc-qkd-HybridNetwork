"""The ETSI GS QKD 004 HTTP/JSON binding, two KME apps talking over the real routes.

tests/test_etsi004_state_machine.py drives the engines directly. This drives
them through `app/etsi004.py` and `HttpPeerLink`, in-process: each app's peer
link is an ASGI transport onto the other app, so the KM-to-KM exchange goes
through the same routers, bodies and HTTP-status mapping as in the service.

The binding is this project's own (V2.1.1 has no wire format); what is pinned
here is what docs/etsi004-binding.md promises: HTTP 200 with the 004 status in
the body, 422 for a malformed request, 404 for an unknown or closed
Key_stream_ID and for the whole binding while it is switched off, and the
peer routes kept out of the OpenAPI schema.
"""
from __future__ import annotations

import base64
import importlib

import httpx
import pytest
from fastapi import FastAPI
from test_etsi004_state_machine import DST, SRC, Clock, cl, make_pool

_engine = importlib.import_module("bb84_kme_app.etsi004_engine")
_peer = importlib.import_module("bb84_kme_app.etsi004_peer")
_router = importlib.import_module("bb84_kme_app.etsi004")
StoredKey = importlib.import_module("bb84_kme_app.keypool").StoredKey

PREFIX = _router.binding()["prefix"]


def make_app(sae: str, peer_sae: str, pool, clock) -> FastAPI:
    app = FastAPI()
    app.include_router(_router.router)
    app.include_router(_router.peer_router)
    app.state.pool = pool
    app.state.etsi004 = _engine.Etsi004Engine(
        sae_id=sae, peer_sae_id=peer_sae, keys=pool, peer=None, clock=clock,
        limits=_router.limits)
    return app


@pytest.fixture
def pair():
    clock = Clock()
    pa, pb = make_pool("ALICE"), make_pool("BOB")
    a, b = make_app("ALICE", "BOB", pa, clock), make_app("BOB", "ALICE", pb, clock)
    a.state.etsi004.peer = _peer.HttpPeerLink("http://bob", transport=httpx.ASGITransport(app=b))
    b.state.etsi004.peer = _peer.HttpPeerLink("http://alice", transport=httpx.ASGITransport(app=a))
    return a, b, pa, pb


@pytest.fixture
def enabled():
    cl.set_overrides({"etsi004": {"endpoint_enabled": True}})
    try:
        yield
    finally:
        cl.clear_overrides()


def client(app: FastAPI) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://kme")


def produce(pa, pb, n: int) -> None:
    for i in range(n):
        b64 = base64.b64encode(bytes([i + 1]) * pa.key_bytes).decode()
        pa._admit(StoredKey(key_id=f"k{i}", key_b64=b64))
        pb._admit(StoredKey(key_id=f"k{i}", key_b64=b64, replicated=True))


async def test_the_binding_is_404_while_switched_off(pair):
    a, *_ = pair
    assert cl.require("etsi004.endpoint_enabled") is False, "the shipped config must keep it off"
    async with client(a) as c:
        for path in ("open_connect", "get_key", "close"):
            r = await c.post(f"{PREFIX}/{path}", json={})
            assert r.status_code == 404, path
        r = await c.post("/internal/etsi004/announce", json={"Key_stream_ID": "x"})
        assert r.status_code == 404


async def test_a_stream_end_to_end_over_http(pair, enabled):
    a, b, pa, pb = pair
    async with client(a) as ca, client(b) as cb:
        r = (await ca.post(f"{PREFIX}/open_connect",
                           json={"source": SRC, "destination": DST})).json()
        assert r["status"] == 1
        ksid = r["Key_stream_ID"]
        assert r["QoS"]["Key_chunk_size"] == pa.key_bytes      # bytes, one produced key
        r = (await cb.post(f"{PREFIX}/open_connect",
                           json={"source": DST, "destination": SRC, "Key_stream_ID": ksid})).json()
        assert r["status"] == 0
        produce(pa, pb, pa.low_watermark + 2)
        # BOB first: his KME asks ALICE's over /internal/etsi004/allocate, and
        # ALICE's pushes the chunk back over /internal/etsi004/chunk.
        rb = (await cb.post(f"{PREFIX}/get_key", json={"Key_stream_ID": ksid})).json()
        ra = (await ca.post(f"{PREFIX}/get_key", json={"Key_stream_ID": ksid, "index": 0})).json()
        assert rb["status"] == ra["status"] == 0
        assert rb["index"] == ra["index"] == 0
        assert rb["Key_buffer"] == ra["Key_buffer"]
        assert len(base64.b64decode(ra["Key_buffer"])) == pa.key_bytes
        for c in (ca, cb):
            r = (await c.post(f"{PREFIX}/close", json={"Key_stream_ID": ksid})).json()
            assert r["status"] == 0
        # Closed: GET_KEY and CLOSE both answer 404 now (T20).
        for path in ("get_key", "close"):
            r = await ca.post(f"{PREFIX}/{path}", json={"Key_stream_ID": ksid})
            assert r.status_code == 404, path


@pytest.mark.parametrize("body", [
    {"source": SRC, "destination": DST, "Key_stream_ID": "not-a-uuid"},
    {"source": SRC, "destination": DST, "unknown_field": 1},
    {"source": SRC, "destination": DST, "QoS": {"Timeout": 2**32}},
    {"source": SRC, "destination": DST, "QoS": {"TTL": -1}},
    {"source": "no scheme", "destination": DST},
    {"destination": DST},
], ids=["uuid", "extra", "uint32-high", "uint32-low", "uri", "missing"])
async def test_a_malformed_open_connect_is_422(pair, enabled, body):
    a, *_ = pair
    async with client(a) as c:
        r = await c.post(f"{PREFIX}/open_connect", json=body)
    assert r.status_code == 422


async def test_an_unknown_key_stream_id_is_404(pair, enabled):
    a, *_ = pair
    ksid = "3f0e0d0c-0b0a-4908-8706-050403020100"
    async with client(a) as c:
        for path in ("get_key", "close"):
            r = await c.post(f"{PREFIX}/{path}", json={"Key_stream_ID": ksid})
            assert r.status_code == _router.binding()["unknown_ksid_http"] == 404, path


async def test_a_conflicting_chunk_is_409_and_a_repeat_is_accepted(pair, enabled):
    a, b, pa, pb = pair
    async with client(a) as ca, client(b) as cb:
        ksid = (await ca.post(f"{PREFIX}/open_connect",
                              json={"source": SRC, "destination": DST})).json()["Key_stream_ID"]
        await cb.post(f"{PREFIX}/open_connect",
                      json={"source": DST, "destination": SRC, "Key_stream_ID": ksid})
    link = a.state.etsi004.peer
    one = base64.b64encode(b"\x01" * pa.key_bytes).decode()
    two = base64.b64encode(b"\x02" * pa.key_bytes).decode()
    await link.chunk(ksid, 0, ["k"], one, 1.0)
    await link.chunk(ksid, 0, ["k"], one, 1.0)            # the same bytes again: fine
    with pytest.raises(_engine.ChunkConflict):
        await link.chunk(ksid, 0, ["k"], two, 1.0)


def test_the_peer_routes_are_not_in_the_schema(pair):
    a, *_ = pair
    paths = set(a.openapi()["paths"])
    assert {f"{PREFIX}/open_connect", f"{PREFIX}/get_key", f"{PREFIX}/close"} <= paths
    assert not [p for p in paths if p.startswith("/internal/")]
