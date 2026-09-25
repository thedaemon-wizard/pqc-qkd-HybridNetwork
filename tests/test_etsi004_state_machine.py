"""The ETSI GS QKD 004 V2.1.1 engine, two KMEs wired together in memory.

Each KME gets a real KeyPool (the producer not started; keys are admitted by
hand, as `_record` + `/internal/sync` would) and an Etsi004Engine; the two
engines talk through `MemPeer`, which maps a peer's UnknownStream to
PeerLostStream exactly as HttpPeerLink maps an HTTP 404.

What must hold, beyond "each transition does what the spec file says":

  * both applications read the SAME bytes for the same index;
  * a KME never hands its application a chunk the peer has not stored;
  * a 004 chunk never takes the pool below the ETSI 014 floor, and never makes
    a key resolvable through 014 `dec_keys` on either KME;
  * with no 004 demand, the producer gate is what it was before 004 existed.

`test_every_endpoint_transition_is_exercised` replays every scenario and
checks that together they took every transition the spec file scopes to the
endpoint -- so a transition added to the file without a test fails here.
"""
from __future__ import annotations

import asyncio
import base64
import dataclasses
import importlib
import json
import os
from collections import deque
from pathlib import Path

import pytest
from conftest import load_service_app

REPO = Path(__file__).resolve().parents[1]
# CONFIG_PATH is resolved when config_loader is first imported.
os.environ.setdefault("QKD_PARAMS_FILE", str(REPO / "config" / "qkd_params.yaml"))

load_service_app("bb84-kme", "bb84_kme_app")
_keypool = importlib.import_module("bb84_kme_app.keypool")
_engine = importlib.import_module("bb84_kme_app.etsi004_engine")
_router = importlib.import_module("bb84_kme_app.etsi004")
cl = importlib.import_module("bb84_kme_app.config_loader")

KeyPool, StoredKey, PoolStats = _keypool.KeyPool, _keypool.StoredKey, _keypool.PoolStats
Engine = _engine.Etsi004Engine
UnknownStream = _engine.UnknownStream
PeerUnreachable, PeerTimeout = _engine.PeerUnreachable, _engine.PeerTimeout

SPEC = json.loads(Path(os.environ["ETSI004_SPEC_FILE"]).read_text())
ENDPOINT_TRANSITIONS = {t["id"] for t in SPEC["transitions"] if "endpoint" in t["scope"]}

SRC, DST = "sae://alice/app", "sae://bob/app"


class Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


class MemPeer:
    """PeerLink to another in-process engine. `fail[method]` injects a failure."""

    def __init__(self) -> None:
        self.other: Engine | None = None
        self.fail: dict[str, type[Exception]] = {}

    async def _call(self, name: str, fn, *args):
        if name in self.fail:
            raise self.fail[name](name)
        try:
            return await fn(*args)
        except UnknownStream as e:              # HTTP 404 in the service
            raise _engine.PeerLostStream(str(e)) from e

    async def announce(self, ksid, apps, qos, t):
        await self._call("announce", self.other.on_announce, ksid, apps, qos)

    async def establish(self, ksid, t):
        await self._call("establish", self.other.on_establish, ksid)

    async def allocate(self, ksid, index, t):
        return await self._call("allocate", self.other.on_allocate, ksid, index)

    async def chunk(self, ksid, index, key_ids, data_b64, t):
        await self._call("chunk", self.other.on_chunk, ksid, index, key_ids, data_b64)

    async def close(self, ksid, t):
        await self._call("close", self.other.on_close, ksid)

    async def withdraw(self, ksid, t):
        await self._call("withdraw", self.other.on_withdraw, ksid)


def make_pool(sae_id: str) -> KeyPool:
    p = KeyPool.__new__(KeyPool)
    p.sae_id = sae_id
    p.peer_kme_url = "http://peer.invalid"
    p.capacity = int(cl.require("simulator.pool_max_size"))
    p.low_watermark = int(cl.require("simulator.pool_low_watermark"))
    p._buf = deque(maxlen=p.capacity)
    p._by_id = {}
    p._lock = asyncio.Lock()
    p._wake = asyncio.Event()
    p._stats = PoolStats()
    p._extra_target = 0
    p._round_ms_total = 0.0
    p._withdrawn = {}
    return p


class Pair:
    """ALICE (allocator) and BOB, each with a pool, an engine and a peer link."""

    def __init__(self, limits=None) -> None:
        self.clock = Clock()
        self.pa, self.pb = make_pool("ALICE"), make_pool("BOB")
        self.la, self.lb = MemPeer(), MemPeer()
        lim = limits or _router.limits
        self.a = Engine(sae_id="ALICE", peer_sae_id="BOB", keys=self.pa, peer=self.la,
                        clock=self.clock, limits=lim)
        self.b = Engine(sae_id="BOB", peer_sae_id="ALICE", keys=self.pb, peer=self.lb,
                        clock=self.clock, limits=lim)
        self.la.other, self.lb.other = self.b, self.a
        self.n = 0
        self.seen: set[str] = set()

    def produce(self, count: int, *, at: str = "a") -> None:
        """`count` keys produced at ALICE (or BOB) and replicated to the other."""
        prod, peer = (self.pa, self.pb) if at == "a" else (self.pb, self.pa)
        for _ in range(count):
            self.n += 1
            b64 = base64.b64encode(os.urandom(prod.key_bytes)).decode()
            kid = f"{at}-{self.n}"
            prod._admit(StoredKey(key_id=kid, key_b64=b64))
            peer._admit(StoredKey(key_id=kid, key_b64=b64, replicated=True))

    def rate(self, bps_rounds: int = 10, ms_total: float = 1000.0) -> None:
        """Give both pools a measured production rate."""
        for p in (self.pa, self.pb):
            p._stats.rounds_accepted = bps_rounds
            p._round_ms_total = ms_total

    def note(self, r: dict) -> dict:
        self.seen.add(r["transition"])
        return r

    async def open_pair(self, qos=None) -> str:
        r1 = self.note(await self.a.open_connect(SRC, DST, qos, None))
        assert r1["status"] == 1 and r1["transition"] == "T1"
        ksid = r1["Key_stream_ID"]
        r2 = self.note(await self.b.open_connect(DST, SRC, None, ksid))
        assert r2["status"] == 0 and r2["transition"] == "T5"
        return ksid


def floor_plus(pair: Pair, chunks: int = 1) -> int:
    """Keys ALICE needs for `chunks` one-key chunks above the 014 floor."""
    return pair.pa.low_watermark + chunks


# ------------------------------------------------------------------ scenarios
async def sc_open_and_read(p: Pair) -> None:
    """T1, T5, T10, T11: open, read the same bytes on both sides."""
    r = p.note(await p.a.open_connect(SRC, DST, None, None))
    ksid = r["Key_stream_ID"]
    # T10: the peer application has not opened yet.
    r = p.note(await p.a.get_key(ksid, None, 0))
    assert r["status"] == 3
    r = p.note(await p.b.open_connect(DST, SRC, None, ksid))
    assert r["status"] == 0 and r["transition"] == "T5"
    assert p.a.streams[ksid].state.value == "ESTABLISHED"
    p.produce(floor_plus(p, 2))
    ra = p.note(await p.a.get_key(ksid, None, 0))
    rb = p.note(await p.b.get_key(ksid, None, 0))
    assert (ra["status"], rb["status"]) == (0, 0)
    assert ra["index"] == rb["index"] == 0
    assert ra["Key_buffer"] == rb["Key_buffer"]
    # BOB asks first this time: ALICE allocates on his request and pushes.
    rb = p.note(await p.b.get_key(ksid, None, 0))
    ra = p.note(await p.a.get_key(ksid, None, 0))
    assert rb["index"] == ra["index"] == 1
    assert rb["Key_buffer"] == ra["Key_buffer"]


async def sc_qos_refused(p: Pair) -> None:
    """T2: a size that is not whole keys, an unsupported mimetype, an unmet Min_bps."""
    r = p.note(await p.a.open_connect(SRC, DST, {"Key_chunk_size": p.pa.key_bytes + 1}, None))
    assert r["status"] == 7 and r["Key_stream_ID"] is None
    assert r["QoS"]["Key_chunk_size"] % p.pa.key_bytes == 0
    r = p.note(await p.a.open_connect(SRC, DST, {"Metadata_mimetype": "text/plain"}, None))
    assert r["status"] == 7 and r["QoS"]["Metadata_mimetype"] == "application/json"
    # No round accepted yet: no rate can be promised at all.
    r = p.note(await p.a.open_connect(SRC, DST, {"Min_bps": 1}, None))
    assert r["status"] == 7 and r["QoS"]["Min_bps"] == 0
    p.rate()
    measured = p.pa.production_capacity_bps()
    r = p.note(await p.a.open_connect(SRC, DST, {"Min_bps": int(measured) + 1}, None))
    assert r["status"] == 7 and r["QoS"]["Min_bps"] == int(measured)
    assert not p.a.streams and not p.b.streams


async def sc_peer_unreachable_at_open(p: Pair) -> None:
    """T3: the peer KM cannot be reached, so nothing is registered."""
    p.la.fail["announce"] = PeerUnreachable
    r = p.note(await p.a.open_connect(SRC, DST, None, None))
    assert r["status"] == 4 and r["Key_stream_ID"] is None
    assert not p.a.streams


async def sc_stream_limit(p: Pair) -> None:
    """T4: the KM's stream limit."""
    one = dataclasses.replace(_router.limits(), max_streams=1)
    q = Pair(limits=lambda: one)
    q.note(await q.a.open_connect(SRC, DST, None, None))
    r = q.note(await q.a.open_connect(SRC, DST, None, None))
    assert r["status"] == 4 and r["transition"] == "T4"
    p.seen |= q.seen


async def sc_predefined_id(p: Pair) -> None:
    """T6 both ways: joined within Timeout, and rolled back on both KMs after it."""
    ksid = "0f0e0d0c-0b0a-4908-8706-050403020100"
    a_call = asyncio.create_task(p.a.open_connect(SRC, DST, {"Timeout": 2000}, ksid))
    await asyncio.sleep(0)
    assert ksid in p.b.streams                       # announced, not yet opened at BOB
    rb = p.note(await p.b.open_connect(DST, SRC, None, ksid))
    ra = p.note(await a_call)
    assert (ra["status"], ra["transition"]) == (0, "T6")
    assert rb["status"] == 0
    # Nobody opens this one: status 6 after Timeout, and no half-open record left.
    other = "1f0e0d0c-0b0a-4908-8706-050403020100"
    r = p.note(await p.a.open_connect(SRC, DST, {"Timeout": 30}, other))
    assert (r["status"], r["transition"]) == (6, "T6")
    assert other not in p.a.streams and other not in p.b.streams


async def sc_ksid_in_use(p: Pair) -> None:
    """T7 (another application pair), T8 (opened twice here), T9 (closed id reused)."""
    ksid = await p.open_pair()
    r = p.note(await p.a.open_connect("sae://carol/app", DST, None, ksid))
    assert (r["status"], r["transition"]) == (5, "T7")
    r = p.note(await p.a.open_connect(SRC, DST, None, ksid))
    assert (r["status"], r["transition"]) == (5, "T8")
    p.note(await p.a.close(ksid))
    p.note(await p.b.close(ksid))
    r = p.note(await p.a.open_connect(SRC, DST, None, ksid))
    assert (r["status"], r["transition"]) == (5, "T9")


async def sc_metadata_too_small(p: Pair) -> None:
    """T12: status 8 holds the index, and the retry gets the same key."""
    ksid = await p.open_pair()
    p.produce(floor_plus(p))
    r = p.note(await p.a.get_key(ksid, None, 1))
    assert r["status"] == 8 and r["index"] == 0 and "Key_buffer" not in r
    need = r["Metadata"]["Metadata_size"]
    # `age` grows while the application reallocates: the size reported must
    # still be enough after it has gained digits (the live stack caught this).
    p.clock.t += 10_000
    r = p.note(await p.a.get_key(ksid, None, need))
    assert r["status"] == 0 and r["index"] == 0
    meta = json.loads(r["Metadata"]["Metadata_buffer"])
    assert set(meta) == {m["name"] for m in SPEC["metadata_keys"]}
    assert meta["hops"] == 0
    rb = p.note(await p.b.get_key(ksid, 0, 0))
    assert rb["Key_buffer"] == r["Key_buffer"]


async def sc_no_key_yet(p: Pair) -> None:
    """T13: status 2 at once, production requested above the 014 floor."""
    ksid = await p.open_pair()
    p.produce(p.pa.low_watermark)                 # exactly the floor: nothing to spare
    r = p.note(await p.a.get_key(ksid, None, 0))
    assert (r["status"], r["transition"]) == (2, "T13")
    assert p.pa._extra_target >= 1, "the producer was not asked for more"
    assert p.pa.dispensable() == p.pa.low_watermark, "the 014 floor was breached"
    p.produce(1)
    r = p.note(await p.a.get_key(ksid, None, 0))
    assert r["status"] == 0
    assert p.pa._extra_target == 0, "the extra demand was not released"


async def sc_peer_timeout_on_push(p: Pair) -> None:
    """T14: no delivery before the peer stored the chunk; the retry delivers."""
    ksid = await p.open_pair()
    p.produce(floor_plus(p))
    p.la.fail["chunk"] = PeerTimeout
    r = p.note(await p.a.get_key(ksid, None, 0))
    assert (r["status"], r["transition"]) == (6, "T14") and "Key_buffer" not in r
    assert 0 not in p.b.streams[ksid].chunks
    del p.la.fail["chunk"]
    ra = p.note(await p.a.get_key(ksid, None, 0))
    rb = p.note(await p.b.get_key(ksid, None, 0))
    assert ra["status"] == rb["status"] == 0
    assert ra["index"] == rb["index"] == 0
    assert ra["Key_buffer"] == rb["Key_buffer"]


async def sc_peer_lost(p: Pair) -> None:
    """T15: the peer unreachable during allocation; then the peer lost the stream."""
    ksid = await p.open_pair()
    p.produce(floor_plus(p, 2))
    p.lb.fail["allocate"] = PeerUnreachable
    r = p.note(await p.b.get_key(ksid, None, 0))
    assert (r["status"], r["transition"]) == (4, "T15")
    del p.lb.fail["allocate"]
    del p.a.streams[ksid]                          # ALICE forgot it (a restart)
    r = p.note(await p.b.get_key(ksid, None, 0))
    assert (r["status"], r["transition"]) == (4, "T15")
    assert p.b.streams[ksid].state.value == "CLOSED"


async def sc_close_and_peer_closed(p: Pair) -> None:
    """T16, T17, T19: close on one side; the other still reads what was allocated."""
    ksid = await p.open_pair()
    p.produce(floor_plus(p))
    ra = p.note(await p.a.get_key(ksid, None, 0))
    r = p.note(await p.a.close(ksid))
    assert (r["status"], r["transition"]) == (0, "T16")
    assert p.a.streams[ksid].state.value == "CLOSING"
    with pytest.raises(UnknownStream):             # closed by this application
        await p.a.get_key(ksid, None, 0)
    rb = p.note(await p.b.get_key(ksid, None, 0))
    assert (rb["status"], rb["transition"]) == (0, "T19")
    assert rb["Key_buffer"] == ra["Key_buffer"]
    p.produce(1)
    rb = p.note(await p.b.get_key(ksid, None, 0))
    assert (rb["status"], rb["transition"]) == (2, "T19"), "a chunk was allocated after CLOSE"
    r = p.note(await p.b.close(ksid))
    assert (r["status"], r["transition"]) == (0, "T17")
    assert p.a.streams[ksid].state.value == p.b.streams[ksid].state.value == "CLOSED"


async def sc_allocator_reads_after_the_peer_closed(p: Pair) -> None:
    """T19 at the allocator: a chunk BOB stored may still be read after BOB closed."""
    ksid = await p.open_pair()
    p.produce(floor_plus(p, 2))
    rb = p.note(await p.b.get_key(ksid, None, 0))
    p.note(await p.b.close(ksid))
    ra = p.note(await p.a.get_key(ksid, None, 0))
    assert (ra["status"], ra["transition"]) == (0, "T19")
    assert ra["Key_buffer"] == rb["Key_buffer"]
    ra = p.note(await p.a.get_key(ksid, None, 0))
    assert (ra["status"], ra["transition"]) == (2, "T19")


async def sc_close_the_peer_never_heard(p: Pair) -> None:
    """ALICE's CLOSE did not reach BOB: she still allocates nothing new for him."""
    ksid = await p.open_pair()
    p.produce(floor_plus(p, 2))
    p.la.fail["close"] = PeerUnreachable
    r = p.note(await p.a.close(ksid))
    assert r["status"] == 0
    assert not p.b.streams[ksid].peer_closed
    held = p.pa.dispensable()
    r = p.note(await p.b.get_key(ksid, None, 0))
    assert r["status"] == 2, "a chunk was allocated after the allocator's application closed"
    assert p.pa.dispensable() == held


async def sc_unknown_and_redelivered(p: Pair) -> None:
    """T20 (unknown or closed id -> 404), T21 (an index read twice)."""
    for call in (p.a.get_key("2f0e0d0c-0b0a-4908-8706-050403020100", None, 0),
                 p.a.close("2f0e0d0c-0b0a-4908-8706-050403020100")):
        with pytest.raises(UnknownStream):
            await call
    p.seen.add("T20")
    ksid = await p.open_pair()
    p.produce(floor_plus(p))
    p.note(await p.a.get_key(ksid, None, 0))
    r = p.note(await p.a.get_key(ksid, 0, 0))
    assert (r["status"], r["transition"]) == (2, "T21")


async def sc_ttl(p: Pair) -> None:
    """T18 (TTL closes an idle stream), T22 (the closed record is dropped)."""
    ksid = await p.open_pair({"TTL": 5})
    p.clock.t += 5
    changed = p.a.sweep()
    assert (ksid, "T18") in changed
    p.seen.add("T18")
    assert p.a.streams[ksid].state.value == "CLOSED"
    p.clock.t += _router.limits().max_ttl_s
    changed = p.a.sweep()
    assert (ksid, "T22") in changed
    p.seen.add("T22")
    assert ksid not in p.a.streams


SCENARIOS = [sc_open_and_read, sc_qos_refused, sc_peer_unreachable_at_open, sc_stream_limit,
             sc_predefined_id, sc_ksid_in_use, sc_metadata_too_small, sc_no_key_yet,
             sc_peer_timeout_on_push, sc_peer_lost, sc_close_and_peer_closed,
             sc_allocator_reads_after_the_peer_closed, sc_close_the_peer_never_heard,
             sc_unknown_and_redelivered, sc_ttl]


@pytest.mark.asyncio
@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda f: f.__name__)
async def test_scenario(scenario):
    await scenario(Pair())


@pytest.mark.asyncio
async def test_every_endpoint_transition_is_exercised():
    seen: set[str] = set()
    for sc in SCENARIOS:
        p = Pair()
        await sc(p)
        seen |= p.seen
    missing = ENDPOINT_TRANSITIONS - seen
    assert not missing, f"transitions in the spec file with no scenario: {sorted(missing)}"
    assert seen <= ENDPOINT_TRANSITIONS | {t["id"] for t in SPEC["transitions"]}


# ----------------------------------------------------------- pool invariants
@pytest.mark.asyncio
async def test_a_004_key_is_never_resolvable_through_014():
    p = Pair()
    ksid = await p.open_pair()
    p.produce(floor_plus(p))
    r = await p.b.get_key(ksid, None, 0)        # allocate + push
    assert r["status"] == 0
    # BOB already delivered it and erased; ALICE still holds hers undelivered.
    kids = p.a.streams[ksid].chunks[0].key_ids
    for kid in kids:
        assert await p.pa.get_by_id(kid) is None, "ALICE's 014 index still has it"
        assert await p.pb.get_by_id(kid) is None, "BOB's 014 index still has it"
        # A replica that arrives late must not bring it back.
        await p.pb.receive_synced(kid, base64.b64encode(b"x" * p.pb.key_bytes).decode())
        assert await p.pb.get_by_id(kid) is None, "a late replica re-entered the 014 index"


@pytest.mark.asyncio
async def test_the_share_cap_bounds_undelivered_chunks():
    p = Pair()
    cap_keys = int(_router.limits().max_pool_share * p.pa.capacity)
    ksid = await p.open_pair({"Key_chunk_size": cap_keys * p.pa.key_bytes})
    p.produce(p.pa.low_watermark + 2 * cap_keys)
    r = await p.b.get_key(ksid, None, 0)        # ALICE now holds chunk 0 undelivered
    assert r["status"] == 0
    r = await p.b.get_key(ksid, None, 0)
    assert r["status"] == 2 and "share" in r["detail"]
    r = await p.a.get_key(ksid, None, 0)        # ALICE reads hers: the share frees up
    assert r["status"] == 0
    r = await p.b.get_key(ksid, None, 0)
    assert r["status"] == 0


def test_the_shipped_share_fits_the_pool_and_a_larger_one_is_refused():
    lim = _router.limits()                          # raises if the shipped file is wrong
    assert 0 < lim.max_pool_share < 1
    cl.set_overrides({"etsi004": {"max_pool_share": 0.9}})
    try:
        with pytest.raises(ValueError, match="max_pool_share"):
            _router.limits()
    finally:
        cl.clear_overrides()


def test_with_no_004_demand_the_producer_gate_is_unchanged():
    """`_extra_target` is 0 unless a stream is short, so the gate reads as before."""
    src = (REPO / "services/bb84-kme/app/keypool.py").read_text()
    assert "if self.dispensable() >= self.low_watermark + self._extra_target:" in src
    assert make_pool("ALICE")._extra_target == 0
    assert "self._extra_target = 0\n" in src.split("def __init__", 1)[1].split("def dispensable", 1)[0]


@pytest.mark.asyncio
async def test_index_origin_is_zero_and_null_means_km_chooses():
    assert SPEC["binding"]["index_origin"] == 0
    p = Pair()
    ksid = await p.open_pair()
    p.produce(floor_plus(p, 3))
    got = [(await p.a.get_key(ksid, None, 0))["index"] for _ in range(3)]
    assert got == [0, 1, 2]
    # An explicit index ahead of the allocation order is refused, not skipped to.
    r = await p.b.get_key(ksid, 5, 0)
    assert r["status"] == 2
