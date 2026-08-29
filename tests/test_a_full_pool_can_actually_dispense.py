"""If the producer thinks the pool is full, `enc_keys` must be able to answer.

Nothing asserted the relationship between the gate that decides whether to
produce and the function that dispenses, and the two disagreed about what "the
pool" means:

    keypool.py  producer gate      len(self._buf) >= self.low_watermark
    keypool.py  replica admission  _admit(StoredKey(..., replicated=True))
    keypool.py  dispensing         next(k for k in _buf if not k.replicated)

`_buf` holds two kinds of key. Replicas arrive from the peer so that `dec_keys`
can resolve the peer's key_IDs; `pop_for_enc` skips them, because when both KMEs
hold the same key only the producer may hand it out. The gate counted both.

A KME whose peer produces faster therefore fills with replicas, crosses the
watermark on them alone, and stops producing. The pool then reads FULL while
every `enc_keys` request answers 503 "key pool empty" -- and `pop_for_enc`'s
`self._wake.set()`, which was plainly meant to fix exactly this, could not: the
producer woke, re-evaluated the same wrong condition, and went back to sleep.

Measured on the public demo before the fix, sampled over two minutes:

    alice   rounds_total 7     pool_size 64 (capacity)   0 rounds/min
    bob     rounds_total 805   pool_size  8 (watermark)  ~3 rounds/min

alice had produced seven keys in her entire lifetime and held sixty-four, so at
least fifty-seven were bob's replicas. Her producer had been asleep for the ~800
rounds bob ran meanwhile. `pool_size: 64` was the largest number on the
dashboard and it meant the node was dead.

The 503 is also the trigger for arnika-project/arnika#43, where the client reads
an already-closed response body and the lane loses key material entirely. Fixing
this gate removes the trigger whatever upstream does.
"""
from __future__ import annotations

import asyncio
import os
import pathlib
import sys
from collections import deque

REPO = pathlib.Path(__file__).resolve().parents[1]

# Before importing app.*: CONFIG_PATH resolves at import time and defaults to a
# path that exists only inside the container. See
# tests/test_skr_is_not_a_sifting_ratio.py:30 for the convention.
os.environ.setdefault("QKD_PARAMS_FILE", str(REPO / "config" / "qkd_params.yaml"))
sys.path.insert(0, str(REPO / "services" / "bb84-kme"))

import pytest  # noqa: E402
from app.backends.base import RoundOutcome  # noqa: E402
from app.keypool import KeyPool, PoolStats, StoredKey  # noqa: E402

WATERMARK = 8


async def _no_peer_sync(key: StoredKey) -> None:
    """Stand in for `_sync_to_peer`, which would open an httpx connection."""
    return None


def _pool(capacity: int = 64) -> KeyPool:
    """A pool with the state under test and nothing else.

    `KeyPool.__init__` resolves a simulation backend, which may need a heavy
    editable submodule; this test is about the buffer arithmetic and has no
    opinion on the backend. test_the_constructed_fields_still_exist below is
    what stops this drifting into testing a shape the real class no longer has.
    """
    p = KeyPool.__new__(KeyPool)
    p._buf = deque(maxlen=capacity)
    p._by_id = {}
    p._lock = asyncio.Lock()
    p._wake = asyncio.Event()
    p._stats = PoolStats()
    p.low_watermark = WATERMARK
    p.capacity = capacity
    # `run()` logs these on entry, so the driven tests need them present.
    p.sae_id = "ALICE"
    p.peer_kme_url = "http://peer.invalid"
    return p


def test_the_constructed_fields_still_exist():
    """Guard the guard: _pool() must not be building an obsolete object.

    Asserted against __init__'s source rather than by constructing one, because
    constructing one is the thing we are avoiding.
    """
    src = (REPO / "services" / "bb84-kme" / "app" / "keypool.py").read_text(
        encoding="utf-8")
    init = src[src.index("    def __init__("):src.index("    # ----", src.index("    def __init__("))]
    for field in ("self._buf", "self._by_id", "self._lock", "self._wake",
                  "self._stats", "self.low_watermark", "self.capacity",
                  "self.sae_id", "self.peer_kme_url"):
        assert f"{field} " in init or f"{field}:" in init, (
            f"{field} is no longer set in KeyPool.__init__; _pool() in this "
            f"file is constructing a shape the class does not have")


# --------------------------------------------------------------------------
# The invariant.
# --------------------------------------------------------------------------

class _StubBackend:
    """Counts rounds. The gate under test decides whether one happens at all."""

    backend_name = "stub"

    def __init__(self) -> None:
        self.calls = 0

    async def run_round(self) -> RoundOutcome:
        self.calls += 1
        return RoundOutcome(
            accepted=True, qber=0.01, key_bytes=b"\x00" * 32,
            n_photons=1, n_sifted=1, intercepted=0, elapsed_ms=0.1,
            skr_bps=0.0, sample_frames=[], backend_meta={},
        )


async def _drive(p: KeyPool, seconds: float = 0.05) -> None:
    """Run the real producer loop briefly, then stop it."""
    task = asyncio.create_task(p.run())
    await asyncio.sleep(seconds)
    p._stopped.set()
    p._wake.set()
    try:
        await asyncio.wait_for(task, timeout=2.0)
    except TimeoutError:                                  # pragma: no cover
        task.cancel()
        raise AssertionError("the producer loop did not stop")


async def test_the_producer_runs_a_round_when_the_pool_is_all_replicas():
    """THE test. It drives `run()`, because the gate lives inside `run()`.

    A first version of this file asserted on `dispensable()` instead and passed
    with the old gate still in place -- it was testing a helper this change
    introduced, not the condition that decides whether a round happens. That is
    the same "passes for a different reason than it claims" defect the suite
    exists to catch, so it is recorded rather than quietly replaced.

    With the old `len(self._buf) >= low_watermark`, a buffer of ten replicas
    reads as full: the loop waits on `_wake` with a 2 s idle timeout and runs
    nothing in the 50 ms below, so `calls` stays 0 and this fails.
    """
    p = _pool()
    stub = _StubBackend()
    p.backend = stub
    p._backend_name = "stub"
    p._stopped = asyncio.Event()
    p._sync_to_peer = _no_peer_sync            # never touch the network

    for i in range(WATERMARK + 2):
        await p.receive_synced(f"peer-{i}", "AAAA")
    assert len(p._buf) >= p.low_watermark, "precondition: the buffer is full"
    assert p.dispensable() == 0, "precondition: none of it can be dispensed"

    await _drive(p)

    assert stub.calls > 0, (
        "the producer ran no round against a pool of undispensable replicas. "
        "It considers the pool full while enc_keys would answer 503, and "
        "nothing will ever change that: pop_for_enc's wake-up re-enters the "
        "same condition")
    assert await p.pop_for_enc(slave_sae_id="BOB") is not None, (
        "rounds ran but produced nothing dispensable")


async def test_the_producer_stops_once_it_has_enough_dispensable_keys():
    """The gate must still gate. Otherwise the fix is just 'always produce'."""
    p = _pool()
    stub = _StubBackend()
    p.backend = stub
    p._backend_name = "stub"
    p._stopped = asyncio.Event()
    p._sync_to_peer = _no_peer_sync

    for i in range(WATERMARK):
        p._admit(StoredKey(key_id=f"local-{i}", key_b64="AAAA",
                           created_at=0.0, replicated=False))
    assert p.dispensable() >= p.low_watermark

    await _drive(p)

    assert stub.calls == 0, (
        f"the producer ran {stub.calls} round(s) with the watermark already "
        f"satisfied by dispensable keys; the gate no longer gates")


async def test_replicas_do_not_count_toward_the_production_gate():
    """Stated directly, because the invariant above can be satisfied two ways."""
    p = _pool()
    for i in range(WATERMARK + 2):
        await p.receive_synced(f"peer-{i}", "AAAA")

    assert len(p._buf) == WATERMARK + 2
    assert p.dispensable() == 0, (
        "peer replicas are counted as dispensable; pop_for_enc skips them, so "
        "the producer would sleep with nothing to hand out")


async def test_locally_produced_keys_do_count():
    """Not vacuous: dispensable() must not simply always return 0."""
    p = _pool()
    for i in range(3):
        p._admit(StoredKey(key_id=f"local-{i}", key_b64="AAAA",
                           created_at=0.0, replicated=False))
    assert p.dispensable() == 3
    assert await p.pop_for_enc(slave_sae_id="BOB") is not None


async def test_a_mixed_pool_counts_only_the_local_half():
    p = _pool()
    for i in range(6):
        await p.receive_synced(f"peer-{i}", "AAAA")
    for i in range(2):
        p._admit(StoredKey(key_id=f"local-{i}", key_b64="AAAA",
                           created_at=0.0, replicated=False))

    assert len(p._buf) == 8
    assert p.dispensable() == 2, "only the two local keys can be dispensed"
    assert p.dispensable() < p.low_watermark, (
        "with 8 keys but only 2 dispensable the producer must keep producing")


async def test_dispensing_reduces_the_count_that_gates_production():
    """Taking the last local key must reopen the gate."""
    p = _pool()
    p._admit(StoredKey(key_id="local-0", key_b64="AAAA",
                       created_at=0.0, replicated=False))
    assert p.dispensable() == 1
    assert await p.pop_for_enc(slave_sae_id="BOB") is not None
    assert p.dispensable() == 0, (
        "a dispensed key still counts as dispensable, so the producer would "
        "not be woken to replace it")


async def test_an_empty_pool_wakes_the_producer():
    """The signal pop_for_enc sends must be one the producer can act on."""
    p = _pool()
    for i in range(WATERMARK + 2):
        await p.receive_synced(f"peer-{i}", "AAAA")
    p._wake.clear()

    assert await p.pop_for_enc(slave_sae_id="BOB") is None
    assert p._wake.is_set(), "pop_for_enc no longer nudges the producer"
    assert p.dispensable() < p.low_watermark, (
        "the producer wakes and re-evaluates its gate; if that gate still says "
        "'full' the wake-up is inert, which is the original defect")


# --------------------------------------------------------------------------
# dec_keys must keep working -- replicas exist for a reason.
# --------------------------------------------------------------------------

async def test_replicas_are_still_resolvable_by_id():
    """The fix must not turn a starvation bug into a dec_keys bug."""
    p = _pool()
    await p.receive_synced("peer-42", "AAAA")
    got = await p.get_by_id("peer-42", master_sae_id="ALICE")
    assert got is not None, (
        "a replicated key can no longer be resolved through dec_keys, which is "
        "the only reason replicas are admitted at all")
    assert got.replicated is True


async def test_a_dispensed_local_key_remains_resolvable():
    """Pinned because pop_for_enc deliberately leaves the key in _by_id."""
    p = _pool()
    p._admit(StoredKey(key_id="local-9", key_b64="AAAA",
                       created_at=0.0, replicated=False))
    sk = await p.pop_for_enc(slave_sae_id="BOB")
    assert sk is not None
    assert await p.get_by_id("local-9", master_sae_id="ALICE") is not None, (
        "the peer resolves this key_ID through dec_keys after we hand it out; "
        "removing it from _by_id would break the other end")


@pytest.mark.parametrize("replicas", [0, 1, WATERMARK, WATERMARK * 4])
async def test_the_gate_never_exceeds_the_local_count(replicas):
    p = _pool()
    for i in range(replicas):
        await p.receive_synced(f"peer-{i}", "AAAA")
    assert p.dispensable() <= len(p._buf)
    assert p.dispensable() == 0
