"""WebUI Backend — FastAPI orchestrator.

Endpoints:
    GET  /api/health
    GET  /api/stack          : container status (alice/bob/bb84-kme-*)
    GET  /api/stats          : aggregated KME + arnika stats
    GET  /api/logs/{name}    : last N log lines from a container
    GET  /api/wg/{node}      : redacted `wg show wg0` for the node. NOT `dump`:
                               that form emits the interface private key and the
                               preshared key in plaintext. See WG_SHOW_CMD.
    POST /api/stack/{action}/{name} : start|stop|restart a service
                             ^^^^^^^ the {name} segment is not optional. Omitting
                             it here is what made scripts/verify-demo-hardening.sh
                             probe a route that does not exist and pass on the 404.
    POST /api/bench/ping     : run ping benchmark
    GET  /api/topology       : graph nodes/edges for D3
"""
from __future__ import annotations

import os
import re
import time
from contextlib import asynccontextmanager
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse

try:
    import docker
    _docker_available = True
except ImportError:
    _docker_available = False

from . import logging_setup, paper_budgets

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

    # The /e2e and /paper-flow orchestrators used to start here. Both pages
    # moved to client-side simulation, nothing has called their endpoints
    # since, and the only thing still reading them was the static budget dict
    # now in `paper_budgets`. Two background tasks per process, for nothing.

    yield
    await app.state.http.aclose()


app = FastAPI(title="PQC-QKD WebUI Backend", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ----------------------- Public-demo hardening (DEMO_MODE) -----------------------
def _truthy(v: str | None) -> bool:
    return str(v or "").strip().lower() in ("1", "true", "yes", "on")

# When DEMO_MODE is on (public multi-user host) the demo is functionally
# EQUIVALENT to full mode EXCEPT the one genuinely dangerous operation —
# container lifecycle control (/api/stack/*), which could take the shared demo
# offline — and a per-IP token-bucket rate-limit on POSTs (abuse protection).
# Backend switching, parameter overrides and (bounded) server-side export saves
# are all ALLOWED: they are reversible / capacity-bounded / rate-limited and
# cannot damage the shared host. Local full-stack and the cloud real-WG deploy
# run with DEMO_MODE OFF (unchanged behaviour).
DEMO_MODE = _truthy(os.environ.get("DEMO_MODE"))
DEMO_RATE_MAX = int(os.environ.get("DEMO_RATE_MAX", "120"))        # tokens / window
DEMO_RATE_WINDOW_S = float(os.environ.get("DEMO_RATE_WINDOW_S", "60"))
_rate_state: dict[str, tuple[float, float]] = {}                   # ip -> (tokens, ts)

# Container lifecycle control is OPT-IN, not opt-out.
#
# This endpoint can start/stop/restart containers through a mounted
# /var/run/docker.sock, so on a reachable host it is a privilege-escalation
# path, not merely a way to take the demo offline. It used to be enabled by
# default and disabled only when DEMO_MODE was set — meaning a deployment that
# simply forgot the flag exposed it to the internet. That is exactly what
# happened to the public demo: it answered `demo_mode: false` while running the
# full profile with docker.sock mounted.
#
# Inverting the default changes the failure mode: a missing or misspelled
# variable now yields a SAFE deployment (403) rather than an exposed one.
# Enabling it is a deliberate act, and DEMO_MODE additionally vetoes it so the
# two cannot be switched on together by accident.
CONTAINER_CONTROL_ENABLED = (
    _truthy(os.environ.get("ENABLE_CONTAINER_CONTROL")) and not DEMO_MODE
)


@app.middleware("http")
async def demo_rate_limit(request, call_next):
    """Per-IP token-bucket on POST requests, active only in DEMO_MODE."""
    if DEMO_MODE and request.method == "POST":
        ip = request.client.host if request.client else "unknown"
        now = time.monotonic()
        tokens, last = _rate_state.get(ip, (float(DEMO_RATE_MAX), now))
        tokens = min(DEMO_RATE_MAX,
                     tokens + (now - last) * (DEMO_RATE_MAX / DEMO_RATE_WINDOW_S))
        if tokens < 1.0:
            _rate_state[ip] = (tokens, now)
            return JSONResponse(
                {"detail": "rate limit exceeded (demo mode)"}, status_code=429)
        _rate_state[ip] = (tokens - 1.0, now)
    return await call_next(request)


# ----------------------- Health / Stack -----------------------
@app.get("/api/health")
async def health() -> dict[str, Any]:
    return {"status": "ok", "demo_mode": DEMO_MODE}


@app.get("/api/config")
async def config() -> dict[str, Any]:
    """Runtime flags the frontend uses to adapt the UI (e.g. hide controls).

    `container_control` is reported explicitly so the deployment's posture can
    be checked from outside without attempting the dangerous call itself --
    see scripts/verify-demo-hardening.sh.
    """
    return {
        "demo_mode": DEMO_MODE,
        "container_control": CONTAINER_CONTROL_ENABLED,
        "rate_limit": {"max": DEMO_RATE_MAX, "window_s": DEMO_RATE_WINDOW_S}
        if DEMO_MODE else None,
    }


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
    """Return the last `lines` lines of <service>.log as a text/plain download.

    404 when the file is absent, rather than 200 with a comment standing in for
    it. The previous form returned

        # log file <service>.log not found

    under a Content-Disposition header, so asking for a log that does not exist
    produced a *successful* download of a one-line file that looked like a log.
    `/console` did exactly that for both KME containers, and no caller could
    distinguish "no such log" from "the service has been quiet".
    """
    safe = service.replace("/", "_").replace("..", "_")
    known = {f["name"] for f in logging_setup.list_log_files()}
    if f"{safe}.log" not in known:
        raise HTTPException(
            status_code=404,
            detail=f"no log file {safe}.log; available: {sorted(known)}",
        )
    return PlainTextResponse(
        logging_setup.read_tail(safe, lines=int(lines)),
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
    Saves <timestamp>-<safe_name>.<ext> into EXPORT_DIR.  Returns the URL.
    Allowed in DEMO_MODE: the store is capacity-bounded (EXPORT_MAX_FILES FIFO +
    EXPORT_MAX_BYTES/file — tightened via env in the demo profile), names are
    sanitised (no path traversal), and POSTs are per-IP rate-limited."""
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
# `wg show <if> dump` PRINTS SECRETS. From wg(8): the first line is
# "private-key, public-key, listen-port, fwmark" tab-separated, and each peer
# line is "public-key, preshared-key, endpoint, allowed-ips, latest-handshake,
# rx, tx, keepalive". Fields 1 and 2 respectively are the interface private key
# and the preshared key, both in plaintext base64.
#
# This route served that verbatim, unauthenticated, with no DEMO_MODE gate. A
# 2026-08-27 GET of the public demo's /api/wg/alice returned alice's wg0 private
# key and the live preshared key -- and on this stack the preshared key is the
# arnika HKDF(QKD || PQC) output, i.e. the entire product of the key path the
# project exists to demonstrate. Nothing in the frontend has ever called this
# route, so the exposure carried no compensating benefit.
#
# The non-dump form is what wireguard-tools redacts for you: it prints
# "private key: (hidden)" and "preshared key: (hidden)". Use it. Then redact
# again on the way out, so that editing one word of the command back is not by
# itself sufficient to leak. See tests/test_wg_endpoint_redacts_secrets.py.
WG_SHOW_CMD = "wg show wg0"

_WG_SECRET_LINE = re.compile(r"^(\s*(?:private key|preshared key)\s*:).*$", re.M | re.I)


def _redact_wg(text: str) -> str:
    """Remove key material from `wg show` output, failing closed.

    Two layers, because what is being guarded is a one-word edit:

      1. any `private key:` / `preshared key:` value becomes `(hidden)`, which
         is what the non-dump form prints anyway -- so this is a no-op on
         correct input and a rescue on incorrect input;
      2. if the text looks like `dump` output at all, the whole body is
         withheld rather than field-edited. The dump format is positional, and
         a redactor that miscounts columns leaks instead of over-redacting;
         refusing is the only safe response to a shape we did not ask for.
    """
    if "\t" in text and "interface:" not in text:
        return (
            "[withheld] this looks like `wg show ... dump`, whose first field is "
            "the interface private key and whose second per-peer field is the "
            "preshared key. This endpoint serves only the redacted `wg show` "
            f"form; see WG_SHOW_CMD ({WG_SHOW_CMD!r})."
        )
    return _WG_SECRET_LINE.sub(r"\1 (hidden)", text)


@app.get("/api/wg/{node}")
async def wg_show(node: str):
    cli = app.state.docker
    if cli is None:
        raise HTTPException(503, "docker not available")
    try:
        c = cli.containers.get(node)
        rc, out = c.exec_run(WG_SHOW_CMD)
        text = out.decode("utf-8", errors="replace")
    except Exception as e:
        raise HTTPException(404, str(e))
    return {"node": node, "rc": rc, "output": _redact_wg(text)}


# The Eve-control, E2E-orchestrator, Paper-Data-Exchange and WebSocket fan-out
# routes were removed here. Every one of them was fully routed and unreachable:
# the frontend has contained no `new WebSocket(...)` since the simulation pages
# moved client-side, and nothing in the repository -- no page, test, Makefile
# target or CI job -- referenced /api/e2e/*, /api/paper-flow/*, /ws/e2e,
# /ws/paper-flow, /ws/frames, /api/sim/eve or /api/sim/rotate.
#
# The Eve and frames routes were thin proxies to services/bb84-kme, which still
# serves them directly; only the unused pass-through is gone.
#
# See docs/phases.md for the superseded design.


# ----------------------- Stack control -----------------------
@app.post("/api/stack/{action}/{name}")
async def stack_action(action: str, name: str):
    # Opt-in, so that forgetting a flag fails closed rather than open.
    if not CONTAINER_CONTROL_ENABLED:
        raise HTTPException(
            403,
            "container control is disabled; set ENABLE_CONTAINER_CONTROL=1 "
            "(and do not set DEMO_MODE) on a trusted host to enable it",
        )
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


@app.get("/api/sim/params/editable")
async def sim_params_editable_proxy():
    """Editable parameter descriptors + current effective values (from KME A)."""
    async with httpx.AsyncClient(timeout=2.0) as client:
        r = await client.get(f"{KME_A_URL}/sim/params/editable")
        return r.json()


@app.post("/api/sim/params")
async def sim_params_set_proxy(req: dict[str, Any]):
    """Apply UI parameter overrides to BOTH KMEs (in-memory; config is default)."""
    last: dict[str, Any] | None = None
    async with httpx.AsyncClient(timeout=5.0) as client:
        for url in (KME_A_URL, KME_B_URL):
            try:
                r = await client.post(f"{url}/sim/params", json=req)
                if r.status_code >= 400:
                    raise HTTPException(r.status_code, r.text)
                last = r.json()
            except HTTPException:
                raise
            except Exception as e:
                log.warning("param set on %s failed: %s", url, e)
    return {"ok": True, "kme": last}


@app.post("/api/sim/params/reset")
async def sim_params_reset_proxy():
    """Drop UI overrides on both KMEs — revert to config defaults."""
    async with httpx.AsyncClient(timeout=5.0) as client:
        for url in (KME_A_URL, KME_B_URL):
            try:
                await client.post(f"{url}/sim/params/reset")
            except Exception as e:
                log.warning("param reset on %s failed: %s", url, e)
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


@app.post("/api/pqc/interop")
async def pqc_interop_proxy(req: dict[str, Any]):
    """Proxy the liboqs-vs-browser ML-KEM interoperability check.

    The browser cannot reach pqc-validator directly, and this is the one call
    on the /pqc page that constitutes an actual cross-check rather than a
    comparison of byte counts.
    """
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            r = await client.post(f"{PQC_VALIDATOR_URL}/api/interop/mlkem", json=req)
        except httpx.HTTPError as e:
            raise HTTPException(503, f"pqc-validator unavailable: {e}")
    if r.status_code >= 400:
        raise HTTPException(r.status_code, r.text)
    return r.json()


@app.post("/api/pqc/roundtrip")
async def pqc_roundtrip(req: dict[str, Any]):
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(f"{PQC_VALIDATOR_URL}/api/roundtrip", json=req)
            return r.json()
    except Exception as e:
        raise HTTPException(503, f"pqc-validator unavailable: {e}")


@app.post("/api/pqc/agility")
async def pqc_agility(req: dict[str, Any] | None = None):
    """Crypto-agility matrix (ML-KEM + ML-DSA across security levels)."""
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            r = await client.post(f"{PQC_VALIDATOR_URL}/api/agility", json=req or {})
            return r.json()
    except Exception as e:
        raise HTTPException(503, f"pqc-validator unavailable: {e}")


# ----------------------- Implementation verification -----------------------
@app.get("/api/verify/keyrate")
async def verify_keyrate():
    """TNO-vs-closed-form key-rate cross-check (from KME A)."""
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            r = await client.get(f"{KME_A_URL}/sim/keyrate/crosscheck")
            return r.json()
    except Exception as e:
        raise HTTPException(503, f"kme unavailable: {e}")


@app.get("/api/verify/paper-budgets")
async def verify_paper_budgets():
    """Paper packet-budget match (arXiv:2604.05599 Table 1).

    Reads the literature values directly from `paper_budgets`. It used to reach
    into a running paper-flow orchestrator for the same static dict, which meant
    a dead 400-line module had to keep booting with the application, and a 503
    here whenever it had not started yet.
    """
    budgets = paper_budgets.as_dict()
    phases = budgets["phases"]
    total_pkts = sum(int(p.get("packets", 0)) for p in phases)
    total_bytes = sum(int(p.get("bytes", 0)) for p in phases)
    # Compared against the separately transcribed paper totals, NOT against
    # `total_handshake_*`, which is the sum of these very phases. That earlier
    # comparison was a sum against itself -- always true, whatever the paper
    # says -- and /verify displayed it as evidence.
    return {
        "phases": phases,
        "computed_total_packets": total_pkts,
        "computed_total_bytes": total_bytes,
        "paper_total_packets": budgets["paper_total_packets"],
        "paper_total_bytes": budgets["paper_total_bytes"],
        "packets_match": total_pkts == budgets["paper_total_packets"],
        "bytes_match": total_bytes == budgets["paper_total_bytes"],
        "reference": "Spooren et al. arXiv:2604.05599 Evaluation Test 1, Table 1",
    }


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
        except Exception as e:
            # The IPsec branch below logs; this one used to swallow silently, so
            # a WireGuard lane that was never reachable looked identical to one
            # that was simply absent.
            log.warning("wireguard status unavailable: %s", e)
        try:
            c = cli.containers.get("alice-ipsec")
            rc_sas, sas = c.exec_run("swanctl --list-sas")
            rc_conns, conns = c.exec_run("swanctl --list-conns")
            # Check the exit codes. swanctl writes its error text to the same
            # stream as its output, and that text is non-empty, so passing a
            # failed invocation into the parser makes `sas.strip()` truthy and
            # reports status "running" for a charon that is dead. That is the
            # precise "healthy while doing nothing" mode this lane exists to
            # eliminate, reproduced in the status API.
            if rc_sas != 0 or rc_conns != 0:
                detail = (sas if rc_sas != 0 else conns).decode("utf-8", errors="replace")
                log.warning(
                    "swanctl failed in alice-ipsec (list-sas rc=%s, list-conns rc=%s): %s",
                    rc_sas, rc_conns, detail.strip()[:200],
                )
                ipsec_status = {
                    "name": "ipsec",
                    "status": "error",
                    "active_sa": 0,
                    "proposal": None,
                    "last_handshake": None,
                    "pq_key_exchange": None,
                    # Same keys as the success path, so a consumer never has to
                    # branch on which shape it received.
                    "ppk_id": None,
                    "ppk_required": None,
                }
            else:
                ipsec_status = _parse_ipsec_sas(
                    sas.decode("utf-8", errors="replace"),
                    conns.decode("utf-8", errors="replace"),
                )
        except Exception as e:
            log.warning("ipsec status unavailable: %s", e)
    return {"wireguard": wg_status, "ipsec": ipsec_status}


# `swanctl --list-sas` renders an established IKE_SA as e.g.
#   pqcqkd-vpn: #1, ESTABLISHED, IKEv2, 8f3a...:c1d2...
#     local  'alice@pqcqkd.local' @ 10.30.0.20[500]
#     ...
#     AES_GCM_16-256/PRF_HMAC_SHA2_384/ECP_256/ML_KEM_768
#     established 12s ago, reauth in 18s
_SA_PROPOSAL_RE = re.compile(r"^\s{2,}([A-Z0-9_]+(?:-[0-9]+)?(?:/[A-Z0-9_]+)+)\s*$", re.M)
_SA_ESTABLISHED_RE = re.compile(r"established (\d+)([smh]) ago", re.M)
# `swanctl --list-conns` renders a PPK-enabled connection as:
#     ppk: ppk-qkd@pqcqkd.local, required
_CONN_PPK_RE = re.compile(r"^\s*ppk:\s*(\S+?),\s*(required|optional)\s*$", re.M)


def _parse_ipsec_sas(sas: str, conns: str) -> dict[str, Any]:
    """Derive IPsec lane status from real swanctl output.

    Every field is parsed from the daemon. An earlier version returned a
    hardcoded proposal string, so the UI kept advertising RFC 9370 ML-KEM even
    when charon had negotiated something else -- or, as it turned out, when
    charon was not running at all.

    Note the two mechanisms are reported separately and must not be conflated:
      * RFC 9370 (ML-KEM in the proposal) strengthens the key EXCHANGE.
      * RFC 8784 (PPK) mixes the QKD key into SK_d/SK_pi/SK_pr.
    Seeing ML_KEM in the proposal says nothing about whether the PPK is in use.
    """
    established = sas.count("ESTABLISHED")
    status = "established" if established else ("running" if sas.strip() else "absent")

    proposals = _SA_PROPOSAL_RE.findall(sas)
    # The IKE_SA proposal is the first algorithm line; CHILD_SA lines follow.
    proposal = proposals[0] if proposals else None

    age = _SA_ESTABLISHED_RE.search(sas)
    ppk = _CONN_PPK_RE.search(conns)

    return {
        "name": "ipsec",
        "status": status,
        "active_sa": established,
        # None rather than a plausible-looking constant, so the UI can tell
        # "not negotiated yet" apart from "negotiated X".
        "proposal": proposal,
        "last_handshake": f"{age.group(1)}{age.group(2)} ago" if age else None,
        # RFC 9370: an additional ML-KEM key exchange was negotiated.
        "pq_key_exchange": "ML_KEM" in (proposal or "") or None,
        # RFC 8784: the connection is configured to mix a PPK into the key
        # schedule. charon does not report per-SA PPK use over VICI, so this is
        # honestly labelled as configuration, not as proof of use.
        "ppk_id": ppk.group(1) if ppk else None,
        "ppk_required": (ppk.group(2) == "required") if ppk else None,
    }


# ----------------------- Topology -----------------------
@app.get("/api/topology")
async def topology():
    """Static four-node graph: alice, bob and the two KMEs.

    The previous docstring said "in multihop mode include charlie", which no
    code does -- there is no multihop branch and no signal here that would
    indicate one. README described the page as showing Charlie on the strength
    of this line. Adding the branch needs a way to know the profile is active;
    until then the graph is honestly static.
    """
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


