"""BB84-KME FastAPI entrypoint.

Mounts:
    /api/v1/keys/...            ETSI GS QKD 014 (arnika-compatible)
    /internal/sync              Peer KME key sync (Alice<->Bob)
    /sim/eve                    Toggle Eve attack (POST)
    /sim/rotate                 Force immediate BB84 round
    /sim/stats                  Pool & sim statistics
    /ws/frames                  WS stream of recent photon frames
    /metrics                    Prometheus metrics
    /health                     Liveness probe
"""
from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)

from . import config_loader, etsi014, optimizer
from .keypool import KeyPool

from . import logging_setup

log = logging_setup.configure(os.environ.get("SAE_ID", "bb84-kme").lower())

# ------------------------- Prometheus metrics -------------------------
M_ROUNDS = Counter("qkd_rounds_total", "BB84 rounds run", ["outcome"])
M_QBER = Gauge("qkd_qber", "Most recent QBER (0..1)")
M_POOL = Gauge("qkd_pool_size", "Keys currently buffered")
M_ROUND_MS = Histogram(
    "qkd_round_ms",
    "BB84 round duration (ms)",
    buckets=(20, 50, 100, 200, 500, 1000, 2000, 5000),
)
M_INTERCEPT = Counter("qkd_intercepted_photons_total", "Photons intercepted by Eve")


# ------------------------- App lifecycle -------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    sae_id = os.environ.get("SAE_ID", "ALICE")
    peer_url = os.environ.get("PEER_KME_URL", "http://bb84-kme-b:8080")
    config_loader.reload()
    config_loader.start_watchdog(poll_interval_s=1.0)
    pool = KeyPool(
        sae_id=sae_id,
        peer_kme_url=peer_url,
        backend_name=os.environ.get("SIMULATOR_BACKEND"),
    )
    app.state.pool = pool
    app.state.frame_subs: set[asyncio.Queue] = set()
    task = asyncio.create_task(pool.run(), name="bb84-producer")
    metrics_task = asyncio.create_task(_metrics_loop(app), name="metrics-loop")
    log.info("BB84-KME started: SAE=%s peer=%s", sae_id, peer_url)
    try:
        yield
    finally:
        log.info("BB84-KME shutting down")
        await pool.stop()
        task.cancel()
        metrics_task.cancel()
        for t in (task, metrics_task):
            try:
                await t
            except (asyncio.CancelledError, Exception):
                pass


async def _metrics_loop(app: FastAPI) -> None:
    while True:
        try:
            stats = app.state.pool.stats()
            M_QBER.set(stats.last_qber)
            M_POOL.set(stats.pool_size)
            # Counters are set by inc(); we observe deltas via attribute snapshots
            # (simplified: re-sync to current snapshot)
            # Fan out frames to WS subscribers
            if stats.last_frames:
                payload = {
                    "type": "frames",
                    "qber": stats.last_qber,
                    "intercepted_total": stats.intercepted_total,
                    "pool_size": stats.pool_size,
                    "frames": stats.last_frames,
                }
                for q in list(app.state.frame_subs):
                    try:
                        q.put_nowait(payload)
                    except asyncio.QueueFull:
                        pass
        except Exception as e:    # pragma: no cover
            log.warning("metrics loop error: %s", e)
        await asyncio.sleep(1.0)


# ------------------------- FastAPI app -------------------------
app = FastAPI(
    title="BB84-KME (ETSI GS QKD 014)",
    version="0.1.0",
    description="Quantum-physics-simulated BB84 wrapped by an ETSI 014 REST API",
    lifespan=lifespan,
)
app.include_router(etsi014.router)


@app.get("/health", response_class=PlainTextResponse)
async def health() -> str:
    return "ok"


@app.get("/metrics")
async def metrics():
    return PlainTextResponse(generate_latest(), media_type=CONTENT_TYPE_LATEST)


# ------------------------- Internal sync -------------------------
class InternalSync(BaseModel):
    key_ID: str
    key: str


@app.post("/internal/sync")
async def internal_sync(req: InternalSync):
    await app.state.pool.receive_synced(req.key_ID, req.key)
    return {"ok": True}


# ------------------------- Simulator controls -------------------------
class EveCtl(BaseModel):
    enabled: bool
    prob: float = 1.0


@app.post("/sim/eve")
async def sim_eve(ctl: EveCtl):
    if not 0.0 <= ctl.prob <= 1.0:
        raise HTTPException(status_code=400, detail="prob must be in [0,1]")
    app.state.pool.set_eve(ctl.enabled, ctl.prob)
    return {"ok": True, "enabled": ctl.enabled, "prob": ctl.prob}


@app.get("/sim/stats")
async def sim_stats():
    s = app.state.pool.stats()
    return s


@app.post("/sim/rotate")
async def sim_rotate():
    """Hint the producer to run another round immediately by clearing wake."""
    app.state.pool._wake.set()
    return {"ok": True}


# ------------------------- Backend / Optimizer controls -------------------------
class BackendSwitch(BaseModel):
    name: str


@app.post("/sim/backend")
async def sim_backend(req: BackendSwitch):
    try:
        app.state.pool.switch_backend(req.name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    return {"ok": True, "backend": req.name}


@app.get("/sim/params")
async def sim_params():
    return config_loader.params()


@app.post("/sim/reload")
async def sim_reload():
    config_loader.reload()
    return {"ok": True}


@app.post("/sim/optimize")
async def sim_optimize():
    result = await asyncio.to_thread(optimizer.optimize_from_yaml)
    return {
        "method": result.method,
        "mu": result.mu, "nu1": result.nu1, "nu2": result.nu2, "pz": result.pz,
        "skr_per_pulse": result.skr_per_pulse,
        "n_calls": result.n_calls,
        "history_len": len(result.history),
    }


# ------------------------- WebSocket frames -------------------------
@app.websocket("/ws/frames")
async def ws_frames(ws: WebSocket) -> None:
    await ws.accept()
    q: asyncio.Queue = asyncio.Queue(maxsize=16)
    app.state.frame_subs.add(q)
    try:
        while True:
            payload = await q.get()
            await ws.send_json(payload)
    except WebSocketDisconnect:
        pass
    finally:
        app.state.frame_subs.discard(q)
