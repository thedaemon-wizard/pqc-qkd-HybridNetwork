"""KeyPool semantics that the ETSI GS QKD 014 master/slave model depends on.

Two defects motivated these tests:

1. `_by_id` was a plain dict that was never pruned, while `_buf` is a bounded
   deque that evicts silently. The index therefore grew without bound, and
   dec_keys could still resolve keys long after they had left the pool.

2. Keys replicated from the peer KME entered the same pool that enc_keys draws
   from, so BOTH KMEs could dispense the same shared key as a *master*. Alice
   and Bob would then each be handed a different key and the derived PSK would
   never match -- silently, because each side considers its own call a success.
"""

from __future__ import annotations

import asyncio
import base64
import importlib

import pytest

from conftest import load_service_app

load_service_app("bb84-kme", "bb84_kme_app")
_keypool = importlib.import_module("bb84_kme_app.keypool")
KeyPool, StoredKey, PoolStats = _keypool.KeyPool, _keypool.StoredKey, _keypool.PoolStats


def make_pool(capacity: int = 4) -> KeyPool:
    """A KeyPool with the producer never started, so tests drive it directly."""
    pool = KeyPool.__new__(KeyPool)
    pool.sae_id = "ALICE"
    pool.peer_kme_url = "http://peer.invalid"
    pool.capacity = capacity
    pool.low_watermark = 1
    from collections import deque

    pool._buf = deque(maxlen=capacity)
    pool._by_id = {}
    pool._lock = asyncio.Lock()
    pool._wake = asyncio.Event()
    pool._stats = PoolStats()
    return pool


def key(n: int, replicated: bool = False) -> StoredKey:
    return StoredKey(
        key_id=f"key-{n}",
        key_b64=base64.b64encode(bytes([n]) * 32).decode(),
        replicated=replicated,
    )


@pytest.mark.asyncio
async def test_replicated_keys_are_never_dispensed_by_enc_keys():
    """Only the producing KME may act as master for a key."""
    pool = make_pool()
    pool._admit(key(1, replicated=True))
    pool._admit(key(2, replicated=True))

    assert await pool.pop_for_enc(slave_sae_id="BOB") is None, (
        "a KME holding only replicas must report an empty pool rather than "
        "hand out a key its peer is also handing out"
    )


@pytest.mark.asyncio
async def test_enc_keys_skips_replicas_and_takes_local_keys():
    pool = make_pool()
    pool._admit(key(1, replicated=True))
    pool._admit(key(2, replicated=False))
    pool._admit(key(3, replicated=True))

    got = await pool.pop_for_enc(slave_sae_id="BOB")
    assert got is not None and got.key_id == "key-2"

    # The replicas stay put, still resolvable through dec_keys.
    assert await pool.pop_for_enc(slave_sae_id="BOB") is None
    assert (await pool.get_by_id("key-1", master_sae_id="BOB")) is not None
    assert (await pool.get_by_id("key-3", master_sae_id="BOB")) is not None


@pytest.mark.asyncio
async def test_dispensed_key_remains_resolvable_by_the_peer():
    """The master hands out key+key_ID; the slave then resolves it via dec_keys."""
    pool = make_pool()
    pool._admit(key(7))

    issued = await pool.pop_for_enc(slave_sae_id="BOB")
    assert issued is not None

    resolved = await pool.get_by_id(issued.key_id, master_sae_id="ALICE")
    assert resolved is not None
    assert resolved.key_b64 == issued.key_b64


@pytest.mark.asyncio
async def test_id_index_is_bounded_by_pool_capacity():
    """_by_id must not outgrow the ring buffer."""
    pool = make_pool(capacity=4)
    for n in range(20):
        pool._admit(key(n))

    assert len(pool._buf) == 4
    assert len(pool._by_id) == 4, (
        f"_by_id holds {len(pool._by_id)} entries for a 4-key pool -- "
        "the index is leaking evicted keys"
    )
    # The survivors are the newest four, and only those resolve.
    assert set(pool._by_id) == {f"key-{n}" for n in range(16, 20)}
    assert await pool.get_by_id("key-0") is None


@pytest.mark.asyncio
async def test_sync_is_idempotent():
    pool = make_pool()
    await pool.receive_synced("key-1", base64.b64encode(b"\x01" * 32).decode())
    await pool.receive_synced("key-1", base64.b64encode(b"\x01" * 32).decode())
    assert len(pool._buf) == 1


@pytest.mark.asyncio
async def test_synced_keys_are_marked_replicated():
    pool = make_pool()
    await pool.receive_synced("key-9", base64.b64encode(b"\x09" * 32).decode())
    assert pool._by_id["key-9"].replicated is True
