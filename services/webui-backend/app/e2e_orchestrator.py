"""End-to-End Quantum-Secure simulation orchestrator (Phase 10-refined).

Implements the 4-phase data exchange flow from the user's reference image:

    Phase 1  Quantum Plane     : poll bb84-kme-a / -b status, wait for keys
    Phase 2  QKD Key IDs       : pull key from KME-A enc_keys, retrieve at KME-B
                                  by key_ID (mirrors arnika ETSI 014 behaviour)
    Phase 3  PQC Handshake     : HKDF-SHA3-256(qkd ‖ random_pqc) -> 32B PSK
                                  (mirrors Rosenpass + arnika KEY-CONTROL)
    Phase 4  Data Exchange     : encrypt N ping-sized payloads with ChaCha20-Poly1305
                                  using the derived PSK (mirrors WireGuard tunnel)

State machine:  idle -> phase1 -> phase2 -> phase3 -> phase4 -> phase1 (loop)
                paused (frozen)  | reset (back to idle)

Drive control via REST (`/api/e2e/{start,pause,resume,reset,step,mode}`) and
observe via WebSocket `/ws/e2e` (250ms ticks).
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import logging
import os
import secrets
import time
from dataclasses import dataclass, field
from typing import Any, Literal

import httpx
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

log = logging.getLogger("e2e")

KME_A_URL = os.environ.get("KME_A_URL", "http://bb84-kme-a:8080")
KME_B_URL = os.environ.get("KME_B_URL", "http://bb84-kme-b:8080")

Mode = Literal["A", "B", "C"]    # QKD-only / PQC-only / Hybrid


@dataclass(slots=True)
class PhaseRecord:
    phase: int
    started_at: float
    completed_at: float | None = None
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class State:
    status: Literal["idle", "running", "paused"] = "idle"
    current_phase: int = 0                      # 0=idle, 1..4
    mode: Mode = "C"                            # Hybrid by default
    completed_cycles: int = 0
    total_bytes_encrypted: int = 0
    total_packets: int = 0
    last_qkd_key_id: str = ""
    last_psk_prefix_hex: str = ""               # first 16 hex of derived PSK
    history: list[PhaseRecord] = field(default_factory=list)
    last_error: str = ""
    rate_bps: float = 0.0                       # estimated throughput


class E2EOrchestrator:
    """Coroutine-driven state machine, fed by /api/e2e/* control endpoints."""

    PHASE_NAMES = {
        1: "Quantum Plane",
        2: "QKD Key IDs (ETSI 014)",
        3: "PQC Handshake (HKDF-SHA3-256)",
        4: "Data Exchange (ChaCha20-Poly1305)",
    }

    def __init__(self) -> None:
        self.state = State()
        self._tick = asyncio.Event()
        self._stop_evt = asyncio.Event()
        self._lock = asyncio.Lock()
        self._step_request = asyncio.Event()
        self._subs: set[asyncio.Queue] = set()
        self._last_publish = 0.0

    # ------------------------------------------------------------------
    # Control surface (called from FastAPI endpoints)
    # ------------------------------------------------------------------
    async def start(self) -> None:
        async with self._lock:
            self.state.status = "running"
        self._tick.set()

    async def pause(self) -> None:
        async with self._lock:
            self.state.status = "paused"

    async def resume(self) -> None:
        async with self._lock:
            self.state.status = "running"
        self._tick.set()

    async def reset(self) -> None:
        async with self._lock:
            self.state = State(mode=self.state.mode)
        self._tick.set()

    async def step(self) -> None:
        """Advance one phase even when paused (single-stepping)."""
        self._step_request.set()
        self._tick.set()

    async def set_mode(self, mode: Mode) -> None:
        if mode not in ("A", "B", "C"):
            raise ValueError(f"mode must be A/B/C, got {mode!r}")
        async with self._lock:
            self.state.mode = mode

    # ------------------------------------------------------------------
    # Subscriber pub/sub for WebSocket fan-out
    # ------------------------------------------------------------------
    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=32)
        self._subs.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subs.discard(q)

    def snapshot(self) -> dict[str, Any]:
        s = self.state
        return {
            "status": s.status,
            "current_phase": s.current_phase,
            "phase_name": self.PHASE_NAMES.get(s.current_phase, "idle"),
            "mode": s.mode,
            "mode_label": {"A": "QKD-only", "B": "PQC-only",
                           "C": "Hybrid (QKD ‖ PQC)"}[s.mode],
            "completed_cycles": s.completed_cycles,
            "total_bytes_encrypted": s.total_bytes_encrypted,
            "total_packets": s.total_packets,
            "last_qkd_key_id": s.last_qkd_key_id,
            "last_psk_prefix_hex": s.last_psk_prefix_hex,
            "last_error": s.last_error,
            "rate_bps": s.rate_bps,
            "history": [
                {"phase": r.phase, "name": self.PHASE_NAMES.get(r.phase, ""),
                 "started_at": r.started_at,
                 "completed_at": r.completed_at,
                 "detail": r.detail}
                for r in s.history[-20:]
            ],
        }

    async def _publish(self) -> None:
        snap = self.snapshot()
        now = time.time()
        # Throttle to ~4 Hz
        if now - self._last_publish < 0.25:
            return
        self._last_publish = now
        for q in list(self._subs):
            try:
                q.put_nowait(snap)
            except asyncio.QueueFull:
                pass

    # ------------------------------------------------------------------
    # Main run loop
    # ------------------------------------------------------------------
    async def run(self) -> None:
        """Background task; cancel by setting `_stop_evt`."""
        log.info("E2E orchestrator started")
        while not self._stop_evt.is_set():
            # If paused, wait until step/resume
            if self.state.status != "running" and not self._step_request.is_set():
                await self._publish()
                try:
                    await asyncio.wait_for(self._tick.wait(), timeout=0.5)
                except asyncio.TimeoutError:
                    pass
                self._tick.clear()
                continue

            try:
                await self._run_one_cycle()
            except Exception as e:
                log.warning("E2E cycle failed: %s", e)
                async with self._lock:
                    self.state.last_error = str(e)
                    self.state.current_phase = 0
                await asyncio.sleep(1.0)

            self._step_request.clear()
            if self.state.status == "paused":
                # If single-stepping, stop after one cycle
                pass
            await self._publish()

    async def _run_one_cycle(self) -> None:
        t_cycle = time.perf_counter()

        # ------------------------------------------------------------
        # Phase 1 — Quantum Plane (wait until both KMEs have keys)
        # ------------------------------------------------------------
        await self._enter_phase(1)
        ok = False
        async with httpx.AsyncClient(timeout=3.0) as client:
            for _ in range(40):    # max ~10s wait
                try:
                    r_a = await client.get(
                        f"{KME_A_URL}/api/v1/keys/ALICE/status")
                    a_pool = int(r_a.json().get("stored_key_count", 0))
                    if a_pool >= 1:
                        ok = True
                        await self._exit_phase(1, {"alice_pool": a_pool})
                        break
                except Exception as e:
                    log.debug("phase1 polling: %s", e)
                await asyncio.sleep(0.25)
        if not ok:
            await self._exit_phase(1, {"error": "no keys available"})
            return

        # ------------------------------------------------------------
        # Phase 2 — QKD Key IDs over ETSI 014 (arnika behaviour)
        # ------------------------------------------------------------
        await self._enter_phase(2)
        qkd_key_b = b""
        key_id = ""
        if self.state.mode in ("A", "C"):
            try:
                async with httpx.AsyncClient(timeout=3.0) as client:
                    r = await client.get(
                        f"{KME_A_URL}/api/v1/keys/ALICE/enc_keys",
                        params={"number": 1, "size": 256})
                    body = r.json()
                    key_id = body["keys"][0]["key_ID"]
                    qkd_key_b = base64.b64decode(body["keys"][0]["key"])
                    # Mirror retrieval from KME-B by key_ID
                    await client.get(
                        f"{KME_B_URL}/api/v1/keys/BOB/dec_keys",
                        params={"key_ID": key_id})
            except Exception as e:
                await self._exit_phase(2, {"error": f"qkd fetch failed: {e}"})
                return
        else:
            # Mode B: PQC-only — skip QKD fetch
            qkd_key_b = b""
            key_id = "(PQC-only mode)"
        await self._exit_phase(2, {"key_id": key_id,
                                    "qkd_key_len": len(qkd_key_b)})

        # ------------------------------------------------------------
        # Phase 3 — PQC Handshake + HKDF (Rosenpass + arnika KEY-CONTROL)
        # ------------------------------------------------------------
        await self._enter_phase(3)
        pqc_secret = b""
        if self.state.mode in ("B", "C"):
            pqc_secret = secrets.token_bytes(32)   # Rosenpass surrogate
        ikm = qkd_key_b + pqc_secret
        if not ikm:
            await self._exit_phase(3, {"error": "no key material"})
            return
        derived = HKDF(
            algorithm=hashes.SHA3_256(), length=32,
            salt=b"pqcqkd-e2e",
            info=f"mode-{self.state.mode}".encode(),
        ).derive(ikm)
        psk_hex_prefix = derived.hex()[:16]
        await self._exit_phase(3, {
            "psk_prefix": psk_hex_prefix,
            "qkd_bytes": len(qkd_key_b),
            "pqc_bytes": len(pqc_secret),
        })

        # ------------------------------------------------------------
        # Phase 4 — Data Exchange (ChaCha20-Poly1305 over derived PSK)
        # ------------------------------------------------------------
        await self._enter_phase(4)
        aead = ChaCha20Poly1305(derived)
        n_packets = 64
        bytes_sent = 0
        for i in range(n_packets):
            nonce = secrets.token_bytes(12)
            ping_payload = (
                b"PING " + i.to_bytes(4, "big")
                + b" Alice->Bob over Quantum-Secure VPN"
            )
            ct = aead.encrypt(nonce, ping_payload, b"alice->bob")
            bytes_sent += len(ct) + len(nonce)
        elapsed = max(time.perf_counter() - t_cycle, 1e-6)
        async with self._lock:
            self.state.total_bytes_encrypted += bytes_sent
            self.state.total_packets += n_packets
            self.state.completed_cycles += 1
            self.state.last_qkd_key_id = key_id
            self.state.last_psk_prefix_hex = psk_hex_prefix
            self.state.rate_bps = bytes_sent * 8.0 / elapsed
            self.state.last_error = ""
        await self._exit_phase(4, {
            "packets": n_packets,
            "bytes": bytes_sent,
            "rate_mbps": (bytes_sent * 8.0 / elapsed) / 1e6,
        })
        async with self._lock:
            self.state.current_phase = 0

    async def _enter_phase(self, phase: int) -> None:
        async with self._lock:
            self.state.current_phase = phase
            self.state.history.append(
                PhaseRecord(phase=phase, started_at=time.time()))
        await self._publish()

    async def _exit_phase(self, phase: int, detail: dict[str, Any]) -> None:
        async with self._lock:
            for r in reversed(self.state.history):
                if r.phase == phase and r.completed_at is None:
                    r.completed_at = time.time()
                    r.detail = detail
                    break
        await self._publish()
