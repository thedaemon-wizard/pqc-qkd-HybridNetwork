"""Paper Data Exchange orchestrator (Phase 14).

Implements the multi-hop trusted-node Data Exchange protocol described in
references/PQC-Enhanced_QKD_Networks_A_Layered_Approach.pdf (Spooren et al.,
arXiv:2604.05599) and pictured in submodules/arnika-vq's multi-hop diagram
(End Node Alice | Trusted Node(s) | End Node Bob).

Compared to e2e_orchestrator.py (image-1 single-tunnel concept) this module
adds:

* 5 phases instead of 4 — Phase 3 (WireGuard hop handshake) is now distinct
  from Phase 2 (Arnika QKD key_ID exchange)
* Paper-quoted packet counts and byte budgets per phase
* Multi-hop daisy chain — configurable number of trusted nodes
* Failure cascade simulator — drop a layer and watch the 240-720 s cascade
* Optional dual-path mode (two diverse Rosenpass instances over disjoint hops)

The state machine is intentionally synthetic — actual ETSI 014 / WireGuard
traffic generation is delegated to the real services; here we model the
*timing* and *packet budget* faithfully so the WebUI can render the paper's
exact numbers.
"""
from __future__ import annotations

import asyncio
import logging
import secrets
import time
from dataclasses import dataclass, field
from typing import Any, Literal

log = logging.getLogger("paper-flow")

Layer = Literal["qkd", "arnika", "wireguard", "rosenpass", "data"]

# Per-phase budgets from arXiv:2604.05599 §IV-B and §V.
# Quote: "Each session’s handshake produces 3 WG packets (398 B), 2 Arnika
#         packets (78 B) and 4 Rosenpass packets (4772 B)."
PHASE_BUDGETS: dict[int, dict[str, Any]] = {
    1: {"name": "Quantum Plane",
        "packets": 0, "bytes": 0,
        "period_s": None, "grace_s": 0,
        "description": "QKD device generates symmetric key material; "
                       "no IP-layer traffic in this phase."},
    2: {"name": "Arnika QKD key_ID exchange",
        "packets": 2, "bytes": 78,
        "period_s": 120, "grace_s": 180,
        "description": "Arnika fetches QKD key from local ETSI 014 KME and "
                       "negotiates the active key_ID with the neighbour Arnika."},
    3: {"name": "WireGuard hop handshake",
        "packets": 3, "bytes": 398,
        "period_s": 120, "grace_s": 60,
        "description": "Curve25519 + ChaCha20 handshake establishes the "
                       "QKD-secured hop tunnel; the QKD-derived PSK is mixed in."},
    4: {"name": "Rosenpass PQC handshake",
        "packets": 4, "bytes": 4772,
        "period_s": 120, "grace_s": 180,
        "description": "Classic McEliece + Kyber end-to-end PQC handshake "
                       "carried over the chain of QKD-secured WireGuard hops."},
    5: {"name": "Final data tunnel + Data Exchange",
        "packets": 0, "bytes": 0,    # variable, application-defined
        "period_s": 120, "grace_s": 60,
        "description": "Application data tunnel (WireGuard with ChaCha20-Poly1305) "
                       "uses a PSK derived from the Rosenpass output."},
}

TOTAL_HANDSHAKE_PACKETS = sum(p["packets"] for p in PHASE_BUDGETS.values())
TOTAL_HANDSHAKE_BYTES = sum(p["bytes"] for p in PHASE_BUDGETS.values())

# Failure cascade timings from arXiv:2604.05599 §IV-B and §VI.
# QKD loss propagates through layers:
#   t=0 QKD drop
#   t≤180s Arnika injects random PSK → WG hop tunnel handshake fails
#   t=240-300s WG hop tunnel grace expires
#   t=300-360s Rosenpass blocked
#   t=420s Rosenpass random key
#   t=480-540s Final data tunnel handshake fails
#   t≥540s full data-path interruption (worst case 720s)
CASCADE_STAGES: list[tuple[float, Layer, str]] = [
    (0.0,   "qkd",       "QKD plane outage injected"),
    (180.0, "arnika",    "Arnika fails over to random key"),
    (240.0, "wireguard", "WireGuard hop tunnel grace expires"),
    (360.0, "rosenpass", "Rosenpass handshake blocked"),
    (420.0, "rosenpass", "Rosenpass falls over to random PSK"),
    (540.0, "data",      "Final data tunnel handshake fails (early cascade)"),
    (720.0, "data",      "Full data-path interruption (worst case)"),
]


@dataclass(slots=True)
class PhaseRecord:
    phase: int
    name: str
    started_at: float
    completed_at: float | None = None
    packets: int = 0
    bytes_: int = 0
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class CascadeEvent:
    t_offset_s: float
    layer: Layer
    description: str
    triggered_at: float | None = None     # wall-clock when the event fired


@dataclass(slots=True)
class State:
    status: Literal["idle", "running", "paused"] = "idle"
    current_phase: int = 0
    hop_count: int = 4                    # Trusted Nodes between Alice & Bob
    dual_path: bool = False               # Run two diverse Rosenpass paths
    cycles_total: int = 0
    cycles_succeeded: int = 0
    packets_total: int = 0
    bytes_total: int = 0
    last_data_payload_b64: str = ""
    failure_active_layer: Layer | None = None
    failure_started_at: float | None = None
    cascade_schedule: list[CascadeEvent] = field(default_factory=list)
    history: list[PhaseRecord] = field(default_factory=list)


class PaperFlowOrchestrator:
    PHASE_BUDGETS = PHASE_BUDGETS
    CASCADE_STAGES = CASCADE_STAGES
    TOTAL_HANDSHAKE_PACKETS = TOTAL_HANDSHAKE_PACKETS
    TOTAL_HANDSHAKE_BYTES = TOTAL_HANDSHAKE_BYTES

    def __init__(self) -> None:
        self.state = State()
        self._tick = asyncio.Event()
        self._stop = asyncio.Event()
        self._lock = asyncio.Lock()
        self._subs: set[asyncio.Queue] = set()
        self._last_publish = 0.0

    # ------------------------------------------------------------------ control
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
            hop = self.state.hop_count
            dual = self.state.dual_path
            self.state = State(hop_count=hop, dual_path=dual)
        self._tick.set()

    async def set_hop_count(self, n: int) -> None:
        n = max(1, min(10, int(n)))
        async with self._lock:
            self.state.hop_count = n

    async def set_dual_path(self, enabled: bool) -> None:
        async with self._lock:
            self.state.dual_path = bool(enabled)

    async def inject_failure(self, layer: Layer) -> None:
        now = time.time()
        # Build a LAYER-APPROPRIATE cascade: begin at the injected layer's first
        # stage and include only the downstream stages, re-based so the injected
        # layer is t=0. (Previously every button reused the full QKD-origin chain,
        # so e.g. injecting "rosenpass" wrongly began with a QKD outage.)
        stages = self.CASCADE_STAGES
        start_idx = next((i for i, s in enumerate(stages) if s[1] == layer), 0)
        base_t = stages[start_idx][0]
        async with self._lock:
            self.state.failure_active_layer = layer
            self.state.failure_started_at = now
            self.state.cascade_schedule = [
                CascadeEvent(
                    t_offset_s=stage[0] - base_t,
                    layer=stage[1],
                    description=stage[2],
                    triggered_at=now + (stage[0] - base_t),
                )
                for stage in stages[start_idx:]
            ]
        log.info("failure injected: layer=%s (cascade from t=%.0fs, %d events)",
                 layer, base_t, len(self.state.cascade_schedule))

    async def clear_failure(self) -> None:
        async with self._lock:
            self.state.failure_active_layer = None
            self.state.failure_started_at = None
            self.state.cascade_schedule = []

    # ------------------------------------------------------------- subscribers
    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=16)
        self._subs.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subs.discard(q)

    def snapshot(self) -> dict[str, Any]:
        s = self.state
        now = time.time()
        cascade = [
            {
                "t_offset_s": ev.t_offset_s,
                "layer": ev.layer,
                "description": ev.description,
                "triggered_at": ev.triggered_at,
                "fired": (ev.triggered_at is not None and now >= ev.triggered_at),
            }
            for ev in s.cascade_schedule
        ]
        return {
            "status": s.status,
            "current_phase": s.current_phase,
            "current_phase_name": self.PHASE_BUDGETS.get(
                s.current_phase, {"name": "idle"})["name"],
            "hop_count": s.hop_count,
            "dual_path": s.dual_path,
            "cycles_total": s.cycles_total,
            "cycles_succeeded": s.cycles_succeeded,
            "packets_total": s.packets_total,
            "bytes_total": s.bytes_total,
            "last_data_payload_b64": s.last_data_payload_b64,
            "failure": {
                "active_layer": s.failure_active_layer,
                "started_at": s.failure_started_at,
                "cascade": cascade,
            },
            "history": [
                {
                    "phase": h.phase, "name": h.name,
                    "started_at": h.started_at,
                    "completed_at": h.completed_at,
                    "packets": h.packets, "bytes": h.bytes_,
                    "detail": h.detail,
                }
                for h in s.history[-30:]
            ],
            "paper_budgets": {
                "phases": [
                    {"phase": p, **{k: v for k, v in info.items() if k != "name"}, "name": info["name"]}
                    for p, info in self.PHASE_BUDGETS.items()
                ],
                "total_handshake_packets": self.TOTAL_HANDSHAKE_PACKETS,
                "total_handshake_bytes": self.TOTAL_HANDSHAKE_BYTES,
                "mean_10_hop_setup_s": 10.27,
                "mean_100_hop_setup_s": 10.62,
            },
        }

    async def _publish(self) -> None:
        now = time.time()
        if now - self._last_publish < 0.25:
            return
        self._last_publish = now
        snap = self.snapshot()
        for q in list(self._subs):
            try:
                q.put_nowait(snap)
            except asyncio.QueueFull:
                pass

    # ------------------------------------------------------------------ loop
    async def run(self) -> None:
        log.info("PaperFlow orchestrator started")
        while not self._stop.is_set():
            if self.state.status != "running":
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
                log.warning("PaperFlow cycle failed: %s", e)
                await asyncio.sleep(1.0)
            await self._publish()

    async def _run_one_cycle(self) -> None:
        async with self._lock:
            self.state.cycles_total += 1

        accepted = True
        for phase in (1, 2, 3, 4, 5):
            await self._enter_phase(phase)
            failure = self.state.failure_active_layer
            failed_this_phase = False
            if failure:
                # Map active failure layer onto current phase
                if (failure == "qkd" and phase == 1) \
                   or (failure == "arnika" and phase == 2) \
                   or (failure == "wireguard" and phase == 3) \
                   or (failure == "rosenpass" and phase == 4) \
                   or (failure == "data" and phase == 5):
                    failed_this_phase = True
                    accepted = False

            await asyncio.sleep(0.08)   # phase pacing for UI animation

            info = self.PHASE_BUDGETS[phase]
            pkts = info["packets"]
            bytes_ = info["bytes"]
            detail: dict[str, Any] = {
                "period_s": info["period_s"],
                "grace_s": info["grace_s"],
                "failed": failed_this_phase,
            }

            if phase == 5 and not failed_this_phase:
                # Synthesise an actual data payload so the WebUI can display
                # a non-zero "Data Exchange" indicator each cycle.
                payload = secrets.token_bytes(64)
                pkts = 1
                bytes_ = len(payload)
                import base64
                async with self._lock:
                    self.state.last_data_payload_b64 = base64.b64encode(payload).decode()
                detail["data_bytes"] = bytes_

            async with self._lock:
                self.state.packets_total += pkts
                self.state.bytes_total += bytes_
            await self._exit_phase(phase, pkts, bytes_, detail)

            if failed_this_phase:
                # Stop further phases this cycle on failure
                break

        async with self._lock:
            if accepted:
                self.state.cycles_succeeded += 1
            self.state.current_phase = 0
        await self._publish()

    async def _enter_phase(self, phase: int) -> None:
        async with self._lock:
            self.state.current_phase = phase
            self.state.history.append(
                PhaseRecord(phase=phase,
                            name=self.PHASE_BUDGETS[phase]["name"],
                            started_at=time.time()))
        await self._publish()

    async def _exit_phase(self, phase: int, pkts: int, bytes_: int,
                          detail: dict[str, Any]) -> None:
        async with self._lock:
            for h in reversed(self.state.history):
                if h.phase == phase and h.completed_at is None:
                    h.completed_at = time.time()
                    h.packets = pkts
                    h.bytes_ = bytes_
                    h.detail = detail
                    break
        await self._publish()
