"""WebUI Backend — FastAPI orchestrator.

Endpoints:
    GET  /api/health
    GET  /api/stack          : container status (alice/bob/bb84-kme-*)
    GET  /api/stats          : aggregated KME + arnika stats
    GET  /api/logs/{name}    : last N log lines from a container
    GET  /api/wg/{node}      : `wg show wg0 dump` for the node
    POST /api/sim/eve        : forward Eve control to KME-a
    POST /api/sim/rotate     : ask KME-a to rotate
    POST /api/stack/{action} : start|stop|restart a service
    POST /api/bench/ping     : run ping benchmark
    GET  /api/topology       : graph nodes/edges for D3
    WS   /ws/frames          : multiplexed KME frame stream
"""
from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

try:
    import docker
    _docker_available = True
except ImportError:
    _docker_available = False

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)s] %(name)s %(message)s",
)
log = logging.getLogger("webui-backend")

KME_A_URL = os.environ.get("KME_A_URL", "http://bb84-kme-a:8080")
KME_B_URL = os.environ.get("KME_B_URL", "http://bb84-kme-b:8080")
PQC_VALIDATOR_URL = os.environ.get("PQC_VALIDATOR_URL", "http://pqc-validator:8090")


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.http = httpx.AsyncClient(timeout=4.0)
    if _docker_available:
        try:
            app.state.docker = docker.from_env()
        except Exception as e:
            log.warning("docker SDK init failed: %s", e)
            app.state.docker = None
    else:
        app.state.docker = None

    # Phase 10: E2E orchestrator
    from .e2e_orchestrator import E2EOrchestrator
    app.state.e2e = E2EOrchestrator()
    app.state.e2e_task = asyncio.create_task(app.state.e2e.run(),
                                              name="e2e-orchestrator")

    yield
    app.state.e2e_task.cancel()
    try:
        await app.state.e2e_task
    except (asyncio.CancelledError, Exception):
        pass
    await app.state.http.aclose()


app = FastAPI(title="PQC-QKD WebUI Backend", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ----------------------- Health / Stack -----------------------
@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/stack")
async def stack() -> list[dict[str, Any]]:
    """Container status for the main services."""
    names = ["alice", "bob", "bb84-kme-a", "bb84-kme-b", "webui-backend",
             "webui-frontend", "pqc-validator", "alice-ipsec", "bob-ipsec",
             "qkdnetsim-kme"]
    out: list[dict[str, Any]] = []
    cli = app.state.docker
    if cli is None:
        return [{"name": n, "status": "unknown"} for n in names]
    for n in names:
        try:
            c = cli.containers.get(n)
            out.append({
                "name": n,
                "status": c.status,
                "image": c.image.tags[0] if c.image.tags else "",
                "started_at": c.attrs.get("State", {}).get("StartedAt"),
            })
        except Exception:
            out.append({"name": n, "status": "absent"})
    return out


# ----------------------- Stats -----------------------
@app.get("/api/stats")
async def stats():
    async with httpx.AsyncClient(timeout=2.0) as client:
        results: dict[str, Any] = {}
        for label, url in (("alice", KME_A_URL), ("bob", KME_B_URL)):
            try:
                r = await client.get(f"{url}/sim/stats")
                results[label] = r.json()
            except Exception as e:
                results[label] = {"error": str(e)}
        return results


# ----------------------- Logs -----------------------
@app.get("/api/logs/{name}")
async def logs(name: str, tail: int = 200) -> dict[str, str]:
    cli = app.state.docker
    if cli is None:
        raise HTTPException(503, "docker not available")
    try:
        c = cli.containers.get(name)
        data = c.logs(tail=tail).decode("utf-8", errors="replace")
    except Exception as e:
        raise HTTPException(404, str(e))
    return {"name": name, "log": data}


# ----------------------- WireGuard show -----------------------
@app.get("/api/wg/{node}")
async def wg_show(node: str):
    cli = app.state.docker
    if cli is None:
        raise HTTPException(503, "docker not available")
    try:
        c = cli.containers.get(node)
        rc, out = c.exec_run("wg show wg0 dump")
        return {"node": node, "rc": rc, "output": out.decode("utf-8", errors="replace")}
    except Exception as e:
        raise HTTPException(404, str(e))


# ----------------------- Eve control -----------------------
class EveCtl(BaseModel):
    enabled: bool
    prob: float = 1.0


@app.post("/api/sim/eve")
async def sim_eve(ctl: EveCtl):
    # Apply to BOTH KMEs so both producers see consistent attack
    async with httpx.AsyncClient(timeout=2.0) as client:
        for url in (KME_A_URL, KME_B_URL):
            try:
                await client.post(f"{url}/sim/eve", json=ctl.model_dump())
            except Exception as e:
                log.warning("eve forward to %s failed: %s", url, e)
    return {"ok": True}


@app.post("/api/sim/rotate")
async def sim_rotate():
    async with httpx.AsyncClient(timeout=2.0) as client:
        for url in (KME_A_URL, KME_B_URL):
            try:
                await client.post(f"{url}/sim/rotate")
            except Exception as e:
                log.warning("rotate %s failed: %s", url, e)
    return {"ok": True}


# ----------------------- Stack control -----------------------
@app.post("/api/stack/{action}/{name}")
async def stack_action(action: str, name: str):
    cli = app.state.docker
    if cli is None:
        raise HTTPException(503, "docker not available")
    if action not in {"start", "stop", "restart"}:
        raise HTTPException(400, "action must be start|stop|restart")
    try:
        c = cli.containers.get(name)
        getattr(c, action)()
    except Exception as e:
        raise HTTPException(500, str(e))
    return {"ok": True, "action": action, "name": name}


# ----------------------- Physics params (proxy to KME A) -----------------------
@app.get("/api/sim/params")
async def sim_params_proxy():
    async with httpx.AsyncClient(timeout=2.0) as client:
        r = await client.get(f"{KME_A_URL}/sim/params")
        return r.json()


@app.post("/api/sim/backend")
async def sim_backend_proxy(req: dict[str, Any]):
    async with httpx.AsyncClient(timeout=5.0) as client:
        for url in (KME_A_URL, KME_B_URL):
            try:
                await client.post(f"{url}/sim/backend", json=req)
            except Exception as e:
                log.warning("backend switch on %s failed: %s", url, e)
    return {"ok": True}


@app.post("/api/sim/optimize")
async def sim_optimize_proxy():
    async with httpx.AsyncClient(timeout=60.0) as client:
        r = await client.post(f"{KME_A_URL}/sim/optimize")
        return r.json()


# ----------------------- PQC Validator proxy -----------------------
@app.get("/api/pqc/algorithms")
async def pqc_algos():
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            r = await client.get(f"{PQC_VALIDATOR_URL}/api/algorithms")
            return r.json()
    except Exception as e:
        raise HTTPException(503, f"pqc-validator unavailable: {e}")


@app.post("/api/pqc/roundtrip")
async def pqc_roundtrip(req: dict[str, Any]):
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(f"{PQC_VALIDATOR_URL}/api/roundtrip", json=req)
            return r.json()
    except Exception as e:
        raise HTTPException(503, f"pqc-validator unavailable: {e}")


# ----------------------- VPN Protocols (Phase 9-A) -----------------------
@app.get("/api/vpn/protocols")
async def vpn_protocols():
    """Return live status of both VPN lanes (WireGuard + IPsec/IKEv2)."""
    cli = app.state.docker
    wg_status: dict[str, Any] = {"name": "wireguard", "status": "absent"}
    ipsec_status: dict[str, Any] = {"name": "ipsec", "status": "absent"}

    if cli is not None:
        try:
            c = cli.containers.get("alice")
            rc, out = c.exec_run("wg show wg0")
            wg_text = out.decode("utf-8", errors="replace")
            wg_status = {
                "name": "wireguard",
                "status": "established" if rc == 0 and "latest handshake" in wg_text else "running",
                "active_sa": 1 if "latest handshake" in wg_text else 0,
                "proposal": "ChaCha20-Poly1305 + Noise + PSK",
                "last_handshake": "via wg show",
            }
        except Exception:
            pass
        try:
            c = cli.containers.get("alice-ipsec")
            rc, out = c.exec_run("swanctl --list-sas")
            text = out.decode("utf-8", errors="replace")
            established = "ESTABLISHED" in text
            ipsec_status = {
                "name": "ipsec",
                "status": "established" if established else "running",
                "active_sa": text.count("ESTABLISHED"),
                "proposal": "aes256gcm16-sha256-ecp256-ke1_ml_kem_768 (RFC 9370)",
                "last_handshake": "via swanctl",
            }
        except Exception:
            pass
    return {"wireguard": wg_status, "ipsec": ipsec_status}


# ----------------------- Topology -----------------------
@app.get("/api/topology")
async def topology():
    """Static graph; in multihop mode include charlie."""
    nodes = [
        {"id": "alice", "type": "node", "label": "Alice (WG + arnika + RP)"},
        {"id": "bob",   "type": "node", "label": "Bob (WG + arnika + RP)"},
        {"id": "kme-a", "type": "kme",  "label": "BB84 KME (Alice)"},
        {"id": "kme-b", "type": "kme",  "label": "BB84 KME (Bob)"},
    ]
    edges = [
        {"source": "alice", "target": "bob",   "label": "WireGuard tunnel (PSK=HKDF(QKD‖PQC))"},
        {"source": "alice", "target": "kme-a", "label": "ETSI 014"},
        {"source": "bob",   "target": "kme-b", "label": "ETSI 014"},
        {"source": "kme-a", "target": "kme-b", "label": "BB84 quantum + classical channel"},
    ]
    return {"nodes": nodes, "edges": edges}


# ----------------------- E2E orchestrator (Phase 10) -----------------------
class E2EMode(BaseModel):
    mode: str   # "A" | "B" | "C"


@app.get("/api/e2e/state")
async def e2e_state():
    return app.state.e2e.snapshot()


@app.post("/api/e2e/start")
async def e2e_start():
    await app.state.e2e.start()
    return {"ok": True, "status": app.state.e2e.state.status}


@app.post("/api/e2e/pause")
async def e2e_pause():
    await app.state.e2e.pause()
    return {"ok": True, "status": app.state.e2e.state.status}


@app.post("/api/e2e/resume")
async def e2e_resume():
    await app.state.e2e.resume()
    return {"ok": True, "status": app.state.e2e.state.status}


@app.post("/api/e2e/reset")
async def e2e_reset():
    await app.state.e2e.reset()
    return {"ok": True}


@app.post("/api/e2e/step")
async def e2e_step():
    await app.state.e2e.step()
    return {"ok": True}


@app.post("/api/e2e/mode")
async def e2e_set_mode(req: E2EMode):
    try:
        await app.state.e2e.set_mode(req.mode)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"ok": True, "mode": req.mode}


@app.websocket("/ws/e2e")
async def ws_e2e(ws: WebSocket):
    await ws.accept()
    q = app.state.e2e.subscribe()
    try:
        # send initial snapshot
        await ws.send_json(app.state.e2e.snapshot())
        while True:
            payload = await q.get()
            await ws.send_json(payload)
    except WebSocketDisconnect:
        pass
    except Exception as e:
        log.warning("ws_e2e error: %s", e)
    finally:
        app.state.e2e.unsubscribe(q)


# ----------------------- WebSocket fan-out -----------------------
@app.websocket("/ws/frames")
async def ws_frames(ws: WebSocket):
    await ws.accept()
    url = KME_A_URL.replace("http", "ws") + "/ws/frames"
    try:
        import websockets
        async with websockets.connect(url) as upstream:
            while True:
                payload = await upstream.recv()
                await ws.send_text(payload)
    except WebSocketDisconnect:
        pass
    except Exception as e:
        try:
            await ws.send_json({"type": "error", "message": str(e)})
        except Exception:
            pass
