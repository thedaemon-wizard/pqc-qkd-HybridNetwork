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
        self.backend: KeyProducer = make_backend(self._backend_name, cfg_from_yaml())
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
                self._buf.append(key)
                self._by_id[key.key_id] = key
                self._stats.pool_size = len(self._buf)
                await self._sync_to_peer(key)
            else:
                self._stats.rounds_aborted += 1

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
                           created_at=asyncio.get_event_loop().time())
            self._buf.append(sk)
            self._by_id[key_id] = sk
            self._stats.pool_size = len(self._buf)

    async def pop_for_enc(self) -> StoredKey | None:
        async with self._lock:
            if not self._buf:
                self._wake.set()
                return None
            key = self._buf.popleft()
            self._stats.pool_size = len(self._buf)
        self._wake.set()
        return key

    async def get_by_id(self, key_id: str) -> StoredKey | None:
        return self._by_id.get(key_id)

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
