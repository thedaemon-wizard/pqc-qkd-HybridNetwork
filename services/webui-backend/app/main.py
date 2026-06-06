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

from . import logging_setup

log = logging_setup.configure("webui-backend")

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

    # Phase 14: Paper Data Exchange orchestrator
    from .paper_flow import PaperFlowOrchestrator
    app.state.paper_flow = PaperFlowOrchestrator()
    app.state.paper_flow_task = asyncio.create_task(
        app.state.paper_flow.run(), name="paper-flow-orchestrator")

    yield
    for task_name in ("e2e_task", "paper_flow_task"):
        task = getattr(app.state, task_name, None)
        if task is not None:
            task.cancel()
            try:
                await task
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


# ----------------------- Phase 12-A: file-backed log endpoints -----------------------
# Registered BEFORE the dynamic /api/logs/{name} route so "files" and
# "download/<svc>" are matched literally first.
@app.get("/api/logs/files")
async def list_log_files() -> dict[str, list]:
    """List every *.log* file present in the shared LOG_DIR volume."""
    return {"files": logging_setup.list_log_files()}


@app.get("/api/logs/download/{service}")
async def download_log(service: str, lines: int = 1000):
    """Return the last `lines` lines of <service>.log as a text/plain download."""
    safe = service.replace("/", "_").replace("..", "_")
    text = logging_setup.read_tail(safe, lines=int(lines))
    from fastapi.responses import PlainTextResponse
    return PlainTextResponse(
        text or f"# log file {safe}.log not found\n",
        headers={"Content-Disposition": f'attachment; filename="{safe}.log"'},
    )


# ----------------------- Phase 13: Backend-stored exports -----------------------
# Persist artefacts (PNG, JSON, CSV, GIF, log) into a shared volume, then offer
# them for download via a stable URL. Lets users save/share simulation outputs
# beyond a single browser session.
EXPORT_DIR = os.environ.get("EXPORT_DIR", "/var/lib/pqcqkd-exports")
EXPORT_MAX_BYTES = int(os.environ.get("EXPORT_MAX_BYTES", 50 * 1024 * 1024))
EXPORT_MAX_FILES = int(os.environ.get("EXPORT_MAX_FILES", 200))


def _ensure_export_dir():
    from pathlib import Path
    d = Path(EXPORT_DIR)
    d.mkdir(parents=True, exist_ok=True)
    return d


def _gc_export_dir() -> None:
    """Keep only the most recent EXPORT_MAX_FILES files (oldest deleted first)."""
    from pathlib import Path
    d = Path(EXPORT_DIR)
    if not d.exists():
        return
    files = sorted(d.glob("*"), key=lambda p: p.stat().st_mtime, reverse=True)
    for old in files[EXPORT_MAX_FILES:]:
        try: old.unlink()
        except Exception: pass


@app.post("/api/exports/save")
async def export_save(req: dict):
    """Body: {name: str, ext: str, content_b64: str}
    Saves <timestamp>-<safe_name>.<ext> into EXPORT_DIR.  Returns the URL."""
    import base64
    import re
    import time
    raw_name = str(req.get("name", "export"))
    ext = str(req.get("ext", "bin")).lstrip(".").lower()
    content_b64 = req.get("content_b64")
    if not content_b64:
        raise HTTPException(400, "content_b64 required")
    try:
        data = base64.b64decode(content_b64, validate=False)
    except Exception as e:
        raise HTTPException(400, f"invalid base64: {e}")
    if len(data) > EXPORT_MAX_BYTES:
        raise HTTPException(413, f"payload {len(data)} > limit {EXPORT_MAX_BYTES}")

    safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "-", raw_name)[:80] or "export"
    safe_ext = re.sub(r"[^A-Za-z0-9]+", "", ext)[:8] or "bin"
    ts = time.strftime("%Y%m%d-%H%M%S")
    filename = f"{ts}-{safe_name}.{safe_ext}"

    d = _ensure_export_dir()
    (d / filename).write_bytes(data)
    _gc_export_dir()

    log.info("export saved name=%s ext=%s bytes=%d", safe_name, safe_ext, len(data))
    return {
        "ok": True,
        "filename": filename,
        "size": len(data),
        "url": f"/api/exports/download/{filename}",
    }


@app.get("/api/exports/list")
async def export_list():
    from pathlib import Path
    d = Path(EXPORT_DIR)
    if not d.exists():
        return {"exports": []}
    out: list[dict] = []
    for p in sorted(d.glob("*"), key=lambda x: x.stat().st_mtime, reverse=True):
        try:
            st = p.stat()
            out.append({"name": p.name, "size": st.st_size, "mtime": st.st_mtime,
                        "url": f"/api/exports/download/{p.name}"})
        except FileNotFoundError:
            continue
    return {"exports": out}


@app.get("/api/exports/download/{filename}")
async def export_download(filename: str):
    import re
    from pathlib import Path
    from fastapi.responses import FileResponse
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", filename)[:120]
    if safe != filename or ".." in safe:
        raise HTTPException(400, "invalid filename")
    p = Path(EXPORT_DIR) / safe
    if not p.exists():
        raise HTTPException(404, "not found")
    ct_map = {".png": "image/png", ".gif": "image/gif",
              ".json": "application/json", ".csv": "text/csv",
              ".log": "text/plain", ".txt": "text/plain"}
    return FileResponse(p, media_type=ct_map.get(p.suffix.lower(),
                                                  "application/octet-stream"),
                        filename=safe)


@app.delete("/api/exports/{filename}")
async def export_delete(filename: str):
    import re
    from pathlib import Path
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", filename)[:120]
    if safe != filename or ".." in safe:
        raise HTTPException(400, "invalid filename")
    p = Path(EXPORT_DIR) / safe
    if p.exists():
        p.unlink()
    return {"ok": True}


# ----------------------- Logs (Docker stdout, dynamic by container name) -----------------------
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


# ----------------------- Phase 14: Paper Data Exchange orchestrator -----------------------
class PaperFlowMode(BaseModel):
    hop_count: int | None = None
    dual_path: bool | None = None


class PaperFlowFailure(BaseModel):
    layer: str       # "qkd" | "arnika" | "wireguard" | "rosenpass" | "data"


@app.get("/api/paper-flow/state")
async def paper_flow_state():
    return app.state.paper_flow.snapshot()


@app.post("/api/paper-flow/start")
async def paper_flow_start():
    await app.state.paper_flow.start()
    return {"ok": True, "status": app.state.paper_flow.state.status}


@app.post("/api/paper-flow/pause")
async def paper_flow_pause():
    await app.state.paper_flow.pause()
    return {"ok": True, "status": app.state.paper_flow.state.status}


@app.post("/api/paper-flow/resume")
async def paper_flow_resume():
    await app.state.paper_flow.resume()
    return {"ok": True, "status": app.state.paper_flow.state.status}


@app.post("/api/paper-flow/reset")
async def paper_flow_reset():
    await app.state.paper_flow.reset()
    return {"ok": True}


@app.post("/api/paper-flow/config")
async def paper_flow_config(req: PaperFlowMode):
    if req.hop_count is not None:
        await app.state.paper_flow.set_hop_count(req.hop_count)
    if req.dual_path is not None:
        await app.state.paper_flow.set_dual_path(req.dual_path)
    return {"ok": True,
            "hop_count": app.state.paper_flow.state.hop_count,
            "dual_path": app.state.paper_flow.state.dual_path}


@app.post("/api/paper-flow/inject-failure")
async def paper_flow_inject_failure(req: PaperFlowFailure):
    if req.layer not in ("qkd", "arnika", "wireguard", "rosenpass", "data"):
        raise HTTPException(400, "layer must be qkd/arnika/wireguard/rosenpass/data")
    await app.state.paper_flow.inject_failure(req.layer)  # type: ignore[arg-type]
    return {"ok": True, "layer": req.layer}


@app.post("/api/paper-flow/clear-failure")
async def paper_flow_clear_failure():
    await app.state.paper_flow.clear_failure()
    return {"ok": True}


@app.websocket("/ws/paper-flow")
async def ws_paper_flow(ws: WebSocket):
    await ws.accept()
    q = app.state.paper_flow.subscribe()
    try:
        await ws.send_json(app.state.paper_flow.snapshot())
        while True:
            payload = await q.get()
            await ws.send_json(payload)
    except WebSocketDisconnect:
        pass
    except Exception as e:
        log.warning("ws_paper_flow error: %s", e)
    finally:
        app.state.paper_flow.unsubscribe(q)


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
