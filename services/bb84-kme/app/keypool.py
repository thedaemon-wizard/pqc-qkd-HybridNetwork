"""Async key pool fed by a pluggable KeyProducer backend.

A single shared ring buffer keeps freshly produced 256-bit keys; the producer
task is woken when the pool drops below the low-watermark. Keys carry a UUID
`key_ID` so they can be retrieved later via the ETSI-014 `dec_keys?key_ID=...`
endpoint.

For two-sided synchronisation (Alice's KME and Bob's KME must hold identical
keys), the producer publishes each new key to the peer KME via
`POST /internal/sync`.

Phase 8: all numeric tunables come from BackendConfig (loaded from
config/qkd_params.yaml). No literals in this file.
"""
from __future__ import annotations

import asyncio
import base64
import logging
import uuid
from collections import deque
from dataclasses import dataclass, field

import httpx

from . import config_loader as cl
from .backends import (
    BackendConfig,
    KeyProducer,
    RoundOutcome,
    make_backend,
    resolve_default_backend_name,
)
from .backends.base import cfg_from_yaml

log = logging.getLogger(__name__)


@dataclass(slots=True)
class StoredKey:
    key_id: str
    key_b64: str
    qber: float = 0.0
    intercepted: int = 0
    created_at: float = 0.0
    #: True when this key arrived from the peer KME via POST /internal/sync.
    #: Such a key is a *replica* held so the local SAE can resolve it through
    #: dec_keys. It must never be handed out by enc_keys: only one KME may act
    #: as master for a given key, and if both dispensed from the shared pool the
    #: two ends would hand their SAEs different keys.
    replicated: bool = False


@dataclass(slots=True)
class PoolStats:
    rounds_total: int = 0
    rounds_accepted: int = 0
    rounds_aborted: int = 0
    last_qber: float = 0.0
    last_round_ms: float = 0.0
    last_skr_bps: float = 0.0
    intercepted_total: int = 0
    keys_emitted: int = 0
    pool_size: int = 0
    backend: str = ""
    last_frames: list[dict] = field(default_factory=list)


class KeyPool:
    """Bounded ring buffer of keys with a background producer task."""

    def __init__(self, *, sae_id: str, peer_kme_url: str,
                 backend_name: str | None = None) -> None:
        self.sae_id = sae_id
        self.peer_kme_url = peer_kme_url.rstrip("/")
        self.low_watermark = int(cl.get("simulator.pool_low_watermark", 8))
        self.capacity = int(cl.get("simulator.pool_max_size", 64))

        self._buf: deque[StoredKey] = deque(maxlen=self.capacity)
        self._by_id: dict[str, StoredKey] = {}
        self._lock = asyncio.Lock()
        self._stats = PoolStats()
        self._wake = asyncio.Event()
        self._stopped = asyncio.Event()

        self._backend_name = backend_name or resolve_default_backend_name()
        # Boot resilience: the configured backend may need a heavy submodule
        # (SimQN / SeQUeNCe / Strawberry Fields / TNO) whose editable install
        # was skipped — e.g. the submodule wasn't checked out before
        # `docker compose build`. Rather than crash the whole KME on startup
        # (which surfaces as "container is unhealthy / dependency failed to
        # start"), fall back to the always-present built-in `qutip` backend
        # and log loudly. Operators can switch to the real backend at runtime
        # via POST /sim/backend once its submodule is present.
        try:
            self.backend: KeyProducer = make_backend(self._backend_name, cfg_from_yaml())
        except Exception as e:
            if self._backend_name in ("qutip", "default"):
                raise  # the built-in itself failed — nothing safe to fall back to
            log.error(
                "backend %r unavailable (%s) — falling back to built-in 'qutip'. "
                "Ensure its submodule is checked out before building "
                "(git submodule update --init --recursive).",
                self._backend_name, e,
            )
            self._backend_name = "qutip"
            self.backend = make_backend("qutip", cfg_from_yaml())
        self._stats.backend = self.backend.backend_name

        # Hot-reload: rebuild backend cfg whenever YAML changes
        def _on_change(_raw):
            try:
                self.backend.update_config(cfg_from_yaml())
            except Exception as e:    # pragma: no cover
                log.warning("backend cfg reload failed: %s", e)
        cl.subscribe(_on_change)

    # ------------------------------------------------------------------
    async def run(self) -> None:
        log.info("KeyPool producer starting (SAE=%s backend=%s peer=%s)",
                 self.sae_id, self._backend_name, self.peer_kme_url)
        idle_timeout_s = float(cl.get("simulator.idle_poll_s", 2.0))
        while not self._stopped.is_set():
            if len(self._buf) >= self.low_watermark:
                try:
                    await asyncio.wait_for(self._wake.wait(), timeout=idle_timeout_s)
                except asyncio.TimeoutError:
                    pass
                self._wake.clear()
                continue
            outcome: RoundOutcome = await self.backend.run_round()
            await self._record(outcome)

    async def stop(self) -> None:
        self._stopped.set()
        self._wake.set()

    async def _record(self, r: RoundOutcome) -> None:
        async with self._lock:
            self._stats.rounds_total += 1
            self._stats.last_qber = r.qber
            self._stats.last_round_ms = r.elapsed_ms
            self._stats.last_skr_bps = r.skr_bps
            self._stats.intercepted_total += r.intercepted
            self._stats.last_frames = r.sample_frames
            if r.accepted:
                self._stats.rounds_accepted += 1
                self._stats.keys_emitted += 1
                key = StoredKey(
                    key_id=str(uuid.uuid4()),
                    key_b64=base64.b64encode(r.key_bytes).decode("ascii"),
                    qber=r.qber,
                    intercepted=r.intercepted,
                    created_at=asyncio.get_event_loop().time(),
                )
                self._admit(key)
                self._stats.pool_size = len(self._buf)
                await self._sync_to_peer(key)
            else:
                self._stats.rounds_aborted += 1

    def _admit(self, key: StoredKey) -> None:
        """Insert a key, keeping the id index bounded by the ring buffer.

        `_buf` is a deque(maxlen=capacity) that evicts its oldest entry
        silently. `_by_id` used to be a plain dict that was never pruned, so it
        grew without bound for the process lifetime -- a slow memory leak, and
        one that also let dec_keys resolve keys long after they had been
        evicted from the pool. Evict from both together.
        """
        evicted = self._buf[0] if len(self._buf) == self._buf.maxlen else None
        self._buf.append(key)
        if evicted is not None:
            self._by_id.pop(evicted.key_id, None)
        self._by_id[key.key_id] = key

    async def _sync_to_peer(self, key: StoredKey) -> None:
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                await client.post(
                    f"{self.peer_kme_url}/internal/sync",
                    json={"key_ID": key.key_id, "key": key.key_b64},
                )
        except Exception as e:    # pragma: no cover
            log.warning("peer sync failed: %s", e)

    async def receive_synced(self, key_id: str, key_b64: str) -> None:
        async with self._lock:
            if key_id in self._by_id:
                return
            sk = StoredKey(key_id=key_id, key_b64=key_b64,
                           created_at=asyncio.get_event_loop().time(),
                           replicated=True)
            self._admit(sk)
            self._stats.pool_size = len(self._buf)

    async def pop_for_enc(self, *, slave_sae_id: str | None = None) -> StoredKey | None:
        """Take a locally-produced key to hand to the master SAE (ETSI 014 'Get key').

        Replicas received from the peer KME are skipped. Both KMEs hold the same
        keys so that either side can resolve a key_ID through dec_keys, but only
        the KME that produced a key may dispense it as an encryption key. If
        both dispensed from the shared pool, Alice and Bob would each be handed
        a different key and the derived PSK would never match.
        """
        async with self._lock:
            local = next((k for k in self._buf if not k.replicated), None)
            if local is None:
                self._wake.set()
                return None
            self._buf.remove(local)
            # Deliberately kept in _by_id: the peer will ask for this key_ID via
            # dec_keys, and on this side it is also the master's record of what
            # it handed out. _admit's eviction bounds the index.
            self._stats.pool_size = len(self._buf)
        self._wake.set()
        if slave_sae_id is not None:
            log.debug("enc_keys: key %s issued for slave SAE %s", local.key_id, slave_sae_id)
        return local

    async def get_by_id(self, key_id: str, *,
                        master_sae_id: str | None = None) -> StoredKey | None:
        """Resolve a key by key_ID (ETSI 014 'Get key with key IDs')."""
        sk = self._by_id.get(key_id)
        if sk is None and master_sae_id is not None:
            log.info("dec_keys: unknown key_ID %s requested for master SAE %s",
                     key_id, master_sae_id)
        return sk

    @property
    def key_size_bits(self) -> int:
        """Key size this KME emits, in BITS (GS QKD 014 counts bits, not bytes).

        Sourced from config so the ETSI `size` parameter and the actual key
        length cannot drift apart.
        """
        return int(cl.get("protocol.out_bits_per_key", 256))

    def stats(self) -> PoolStats:
        return PoolStats(
            rounds_total=self._stats.rounds_total,
            rounds_accepted=self._stats.rounds_accepted,
            rounds_aborted=self._stats.rounds_aborted,
            last_qber=self._stats.last_qber,
            last_round_ms=self._stats.last_round_ms,
            last_skr_bps=self._stats.last_skr_bps,
            intercepted_total=self._stats.intercepted_total,
            keys_emitted=self._stats.keys_emitted,
            pool_size=len(self._buf),
            backend=self._stats.backend,
            last_frames=list(self._stats.last_frames),
        )

    # ------------------------------------------------------------------
    def set_eve(self, enabled: bool, prob: float) -> None:
        self.backend.set_eve(enabled, prob)

    def switch_backend(self, name: str) -> None:
        """Live backend swap (called from /api/backend)."""
        self.backend = make_backend(name, cfg_from_yaml())
        self._backend_name = name
        self._stats.backend = self.backend.backend_name
        log.info("switched backend → %s", name)
