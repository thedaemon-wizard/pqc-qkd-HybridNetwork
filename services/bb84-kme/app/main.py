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
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import PlainTextResponse
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)
from pydantic import BaseModel

from . import config_loader, etsi014, logging_setup
from .keypool import KeyPool

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
            except asyncio.CancelledError:
                pass  # expected: we just cancelled it
            except Exception:
                # Anything else means the task died of something real, and
                # shutdown must not be what hides it.
                log.exception("background task %r raised during shutdown", t.get_name())


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


# Dotted parameter paths the WebUI is allowed to override at runtime. The YAML
# file remains the DEFAULT; overrides are in-memory only and reset on restart.
EDITABLE_PARAMS: dict[str, type] = {
    "physical.fiber_attenuation_db_per_km": float,
    "physical.link_length_km": float,
    "physical.detector_efficiency": float,
    "physical.dark_count_rate_hz": float,
    "physical.misalignment_error_ed": float,
    "source.pulse_rate_hz": float,
    "source.intensity_signal_mu": float,
    "source.intensity_decoy_1_nu1": float,
    "source.intensity_decoy_2_nu2": float,
    "source.basis_bias_pz": float,
    "protocol.ec_efficiency_f": float,
    "protocol.qber_threshold_abort": float,
    "simulator.bb84_batch_size": int,
    "eve.enabled": bool,
    "eve.intercept_prob": float,
}


class ParamPatch(BaseModel):
    # Flat mapping of dotted-path -> value, e.g. {"physical.link_length_km": 25}
    patch: dict[str, float | int | bool]


def _expand_dotted(flat: dict[str, object]) -> dict[str, object]:
    """Turn {"a.b": 1} into {"a": {"b": 1}} for nested override merge."""
    nested: dict[str, object] = {}
    for dotted, value in flat.items():
        parts = dotted.split(".")
        cur = nested
        for p in parts[:-1]:
            cur = cur.setdefault(p, {})  # type: ignore[assignment]
        cur[parts[-1]] = value
    return nested


def _path_in(d: dict, dotted: str) -> bool:
    cur = d
    for p in dotted.split("."):
        if not isinstance(cur, dict) or p not in cur:
            return False
        cur = cur[p]
    return True


@app.get("/sim/params/editable")
async def sim_params_editable():
    """Describe which params the UI may edit + their current effective values."""
    ov = config_loader.overrides()
    fields = [
        {
            "path": path,
            "type": typ.__name__,
            "value": config_loader.get(path),
            "overridden": _path_in(ov, path),
        }
        for path, typ in EDITABLE_PARAMS.items()
    ]
    return {"fields": fields, "overrides": ov}


@app.post("/sim/params")
async def sim_params_set(req: ParamPatch):
    """Apply UI parameter overrides (in-memory; YAML untouched; reset on restart)."""
    cleaned: dict[str, object] = {}
    for path, value in req.patch.items():
        if path not in EDITABLE_PARAMS:
            raise HTTPException(status_code=400, detail=f"param not editable: {path}")
        caster = EDITABLE_PARAMS[path]
        try:
            cleaned[path] = caster(value)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400,
                                detail=f"bad value for {path}: {value!r}")
    config_loader.set_overrides(_expand_dotted(cleaned))
    return {"ok": True, "applied": cleaned, "params": config_loader.params()}


@app.post("/sim/params/reset")
async def sim_params_reset():
    """Drop all UI overrides — revert to config/qkd_params.yaml defaults."""
    config_loader.clear_overrides()
    return {"ok": True, "params": config_loader.params()}


# The five states /sim/keyrate/crosscheck can be in. Named, because one bool
# could not tell them apart -- see the note at the return statement below.
#
# AGREE is deliberately NOT extended to cover the both-zero case. "Same order of
# magnitude" is undefined for 0/0, so reporting agreement under a ratio test
# would be a different false claim than the one being removed. The two
# implementations DO agree there, and NEITHER_PREDICTS_A_KEY says exactly that
# without pretending a ratio was computed.
CROSSCHECK_AGREE = "agree"                                # ratio within [0.1, 10]
CROSSCHECK_DISAGREE = "disagree"                          # ratio outside it
CROSSCHECK_NEITHER_KEY = "neither_predicts_a_key"         # both exactly 0
CROSSCHECK_ONE_SIDE_ZERO = "one_side_zero"                # ratio undefined
CROSSCHECK_ENGINE_UNAVAILABLE = "engine_unavailable"      # TNO never produced a rate


def _crosscheck_verdict(ours: float, tno_rate: float | None) -> str:
    """Classify the cross-check without collapsing distinct outcomes.

    Order matters: the zero cases are decided BEFORE the ratio, because
    `tno_rate / ours` raises on ours == 0 and is meaningless when either side
    is 0.
    """
    if tno_rate is None:
        return CROSSCHECK_ENGINE_UNAVAILABLE
    if ours == 0.0 and tno_rate == 0.0:
        return CROSSCHECK_NEITHER_KEY
    if ours == 0.0 or tno_rate == 0.0:
        return CROSSCHECK_ONE_SIDE_ZERO
    return CROSSCHECK_AGREE if 0.1 <= (tno_rate / ours) <= 10.0 else CROSSCHECK_DISAGREE


@app.get("/sim/keyrate/crosscheck")
async def keyrate_crosscheck():
    """Independent-implementation verification: compare OUR closed-form Lo-Ma
    two-decoy key rate against TNO-Quantum's qkd_key_rate engine (Apache-2.0) at
    the current config. Surfaced in the WebUI verification panel."""
    from .backends._skr import asymptotic_skr_per_pulse, total_transmittance
    from .backends.base import cfg_from_yaml
    cfg = cfg_from_yaml()
    eta_total = total_transmittance(
        cfg.detector_efficiency, cfg.fiber_attenuation_db_per_km, cfg.link_length_km)
    Y0 = cfg.dark_count_rate_hz / max(cfg.pulse_rate_hz, 1.0)
    ours = asymptotic_skr_per_pulse(
        Y0=Y0, eta_total=eta_total, e_d=cfg.misalignment_error_ed,
        mu=cfg.intensity_signal_mu, nu1=cfg.intensity_decoy_1_nu1,
        nu2=cfg.intensity_decoy_2_nu2, f_EC=cfg.ec_efficiency_f)

    tno: dict | None = None
    tno_err: str | None = None
    try:
        from .backends.tno_backend import compute_tno_rate
        tno = await asyncio.to_thread(compute_tno_rate, cfg)
    except Exception as e:    # TNO package missing or compute error
        tno_err = str(e)

    tno_rate = tno["rate_per_pulse"] if tno else None
    # `is not None`, not truthiness. `if tno_rate and ...` treats a genuine TNO
    # output of 0.0 as an absent one, so a measured zero serialised
    # `relative_delta: null` -- byte-identical to the engine never running.
    rel = (abs(tno_rate - ours) / ours) if (tno_rate is not None and ours > 0) else None
    verdict = _crosscheck_verdict(ours, tno_rate)
    return {
        "distance_km": cfg.link_length_km,
        "attenuation_db": cfg.fiber_attenuation_db_per_km * cfg.link_length_km,
        "ours_closed_form": {
            "rate_per_pulse": ours,
            "skr_bps": ours * cfg.pulse_rate_hz,
            "method": "Lo-Ma two-decoy (closed form; arXiv:2511.21253)",
        },
        "tno": tno,
        "relative_delta": rel,
        # `verdict`, not `same_order_of_magnitude`.
        #
        # That bool answered five different questions with one `false`, and
        # three of them also produced `relative_delta: null`, so the payload
        # could not tell them apart either. Measured through the real endpoint:
        #
        #   engine never ran      ours=1.23e-02  tno=None      -> false
        #   ran, disagreed 1000x  ours=1.23e-02  tno=12.334    -> false
        #   ran, returned 0.0     ours=1.23e-02  tno=0.0       -> false
        #   both predict no key   ours=0.0       tno=0.0       -> false
        #   ours 0, tno tiny      ours=0.0       tno=1e-09     -> false
        #
        # The fourth is the inversion that matters: two independent
        # implementations agreeing as completely as they can -- neither predicts
        # an extractable key -- rendered on /verify as "review". Reachable with
        # the shipped config at any link beyond 253.51 km, and
        # physical.link_length_km is an unbounded editable field.
        #
        # Renamed rather than kept alongside a new field: a `false` meaning five
        # things is not made honest by adding a sixth value elsewhere, and
        # nothing would have stopped the frontend reading the old one. The field
        # has exactly three readers, all in Verification.tsx.
        "verdict": verdict,
        "error": tno_err,
    }


# `POST /sim/optimize` was here. The ROUTE is deleted; `app/optimizer.py` is not.
#
# The DoS surface was the unauthenticated HTTP entry point, not the maths.
# skopt gp_minimize with 50 evaluations, reachable through the webui-backend
# proxy by any caller, 14.6 s of CPU per request measured on the live public
# demo -- and no caller anywhere in the repository. /physics does the same job
# as a client-side grid search.
#
# `optimize_from_yaml()` stays importable for offline use: it is exercised by
# tests/test_backend_cross_qber.py and documented in docs/phases.md. Removing
# the module too would have deleted a working research capability to fix an
# exposure that deleting one route already fixes.
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
