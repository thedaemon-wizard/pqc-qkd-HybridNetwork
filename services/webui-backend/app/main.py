"""WebUI Backend — FastAPI orchestrator.

Endpoints:
    GET  /api/health
    GET  /api/stack          : container status (alice/bob/bb84-kme-*)
    GET  /api/stats          : aggregated KME + arnika stats
    GET  /api/logs/{name}    : last N log lines from one of LOG_CONTAINERS; any
                               other name is 404 before Docker is asked
    GET  /api/wg/{node}      : redacted `wg show wg0` (the hop tunnel) for one of
                               WG_NODES, plus `data_tunnel`: the same for `wg1`
                               (the end-to-end data tunnel inside wg0), cached
                               per node for WG_SHOW_TTL_S. NOT `dump`: that form
                               emits the interface private key and the preshared
                               key in plaintext. See WG_SHOW_CMD.
    POST /api/stack/{action}/{name} : start|stop|restart a service
                             ^^^^^^^ the {name} segment is not optional. Omitting
                             it here is what made scripts/verify-demo-hardening.sh
                             probe a route that does not exist and pass on the 404.
    POST /api/sim/backend, /api/sim/params, /api/sim/params/reset
                             : live KME overrides; 403 unless
                               ENABLE_LIVE_PARAM_OVERRIDES is set
    GET  /api/topology       : graph nodes/edges for D3

    This module serves no bench route, and never has. The ping benchmark is
    `benchmarks/ping_loop.sh` (run by `make bench`), a shell script that does
    `docker exec alice ping` and writes benchmarks/results/ping_*.log; nothing
    ever wrapped it in a handler. The index above advertised such a route from
    the initial commit, and it answered 404 on the live demo the whole time.
"""
from __future__ import annotations

import os
import re
import time
from contextlib import asynccontextmanager
from typing import Any

import httpx
from fastapi import Depends, FastAPI, HTTPException, Query
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

# How much of an exception's text, a failed command's output or an upstream
# error body goes into a response field or a log line: enough to name the
# failure, not enough to relay a whole log or an upstream page to the caller.
ERROR_TEXT_MAX_CHARS = 200


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


# The release this backend ships in (CHANGELOG.md), kept equal to the frontend's
# package.json version.
app = FastAPI(title="PQC-QKD WebUI Backend", version="0.2.0", lifespan=lifespan)
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
# EQUIVALENT to full mode EXCEPT container lifecycle control (/api/stack/*),
# which could take the shared demo offline. Every mutating verb is rate-limited
# whatever DEMO_MODE says (see demo_rate_limit). Local full-stack and the cloud
# real-WG deploy run with DEMO_MODE OFF.
#
# This comment used to add that backend switching and parameter overrides were
# "reversible ... and cannot damage the shared host". They cannot damage it, but
# they are not private to the visitor who makes them: both KMEs hold ONE
# process-global override set (last write wins), and those KMEs feed arnika's
# QKD half on both live VPN lanes. One visitor's `eve.enabled` or
# `link_length_km: 300` was every visitor's, and every lane's. They are now
# opt-in; see LIVE_PARAM_OVERRIDES_ENABLED.
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

# Live KME overrides are OPT-IN, for the same reason and in the same shape.
#
# POST /api/sim/backend, /api/sim/params and /api/sim/params/reset write to
# state that is process-global on BOTH KMEs: the simulator backend, the
# in-memory override set (eve.enabled, eve.intercept_prob,
# protocol.qber_threshold_abort, link length, ...), and its reset. Those KMEs
# are not a sandbox. They fill the key pool arnika draws the QKD half of every
# PSK from, on both live VPN lanes. On a host with more than one visitor, the
# last writer silently decides what everyone else sees and what both lanes run
# on, which is the multi-user data conflict the public demo must avoid.
#
# /physics already computes key rates in the browser, so turning these routes
# off costs a visitor nothing but the ability to change the shared KMEs. The
# three routes answer 403 with LIVE_PARAM_OVERRIDES_DISABLED_DETAIL; the GET
# routes are unchanged, and GET /api/config reports the flag as
# `live_param_overrides` so the page can say which model its edits reach.
# Parsed exactly like ENABLE_CONTAINER_CONTROL; a missing or misspelled
# variable yields the safe deployment.
LIVE_PARAM_OVERRIDES_ENABLED = _truthy(os.environ.get("ENABLE_LIVE_PARAM_OVERRIDES"))
LIVE_PARAM_OVERRIDES_DISABLED_DETAIL = (
    "live parameter overrides are disabled on this host "
    "(ENABLE_LIVE_PARAM_OVERRIDES=false); edits apply to the in-browser model only"
)


def _require_live_param_overrides() -> None:
    """403 unless this host opted in to shared, process-global KME overrides.

    Attached to the three routes as a dependency, not called from their bodies:
    FastAPI resolves dependencies before it validates the request body, so a
    bodyless POST, or one whose JSON does not match the parameter, is refused
    with the same 403 as a valid one instead of a 422 that says nothing about
    the switch. A body that is not JSON at all still fails in the parser,
    which runs first, with 422.

    Reads the module global at call time, so a test (or an operator poking a
    running process) sees the value that is actually in force.
    """
    if not LIVE_PARAM_OVERRIDES_ENABLED:
        raise HTTPException(403, LIVE_PARAM_OVERRIDES_DISABLED_DETAIL)


@app.middleware("http")
async def demo_rate_limit(request, call_next):
    """Per-IP token-bucket on POST, PUT, PATCH and DELETE requests. ALWAYS ON.

    This was gated on DEMO_MODE. The public demo runs with DEMO_MODE unset --
    `GET /api/config` returns `{"demo_mode": false, "rate_limit": null}` -- so
    on the one host that faces the internet, the limiter was inert.

    That is backwards. DEMO_MODE exists to REMOVE capability (container
    control, privileged nodes); it is not a statement that a host is exposed.
    A rate limit is cheap on a private host and essential on a public one, and
    tying it to a variable that is off in production means the protection is
    absent exactly where it is needed.

    Measured before this change: `POST /api/sim/optimize` (now deleted) cost
    14.6 s of server CPU per unauthenticated request with no throttle at all.

    The name is kept because DEMO_RATE_MAX / DEMO_RATE_WINDOW_S are the
    documented env vars and renaming them would break deployments for nothing.

    The method set is every mutating verb, not just POST. Ungating DEMO_MODE
    closed one hole and left another: `DELETE /api/exports/{filename}` is the
    project's only non-POST mutating route, and it sat outside the limiter
    before and after that change. Measured on the public host: thirty
    consecutive unauthenticated deletes, thirty 200s, no throttle.

    PUT and PATCH are included although no route uses them today, so that
    adding one is not silently adding an unthrottled mutation.
    """
    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        ip = request.client.host if request.client else "unknown"
        now = time.monotonic()
        tokens, last = _rate_state.get(ip, (float(DEMO_RATE_MAX), now))
        tokens = min(DEMO_RATE_MAX,
                     tokens + (now - last) * (DEMO_RATE_MAX / DEMO_RATE_WINDOW_S))
        if tokens < 1.0:
            _rate_state[ip] = (tokens, now)
            return JSONResponse(
                {"detail": "rate limit exceeded"}, status_code=429)
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
        # Reported unconditionally, because the limiter now runs
        # unconditionally. This was `... if DEMO_MODE else None`, which paired
        # with the old DEMO_MODE-gated middleware -- both off together, so the
        # field was at least honest. Leaving it gated after making the limiter
        # always-on would have made /api/config report "no rate limit" on a
        # host that has one, which is the shape of claim this project keeps
        # removing. scripts/verify-demo-hardening.sh reads this field.
        "rate_limit": {"max": DEMO_RATE_MAX, "window_s": DEMO_RATE_WINDOW_S},
        # Whether POST /api/sim/{backend,params,params/reset} reach the shared
        # KMEs. False means /physics edits change only the in-browser model.
        "live_param_overrides": LIVE_PARAM_OVERRIDES_ENABLED,
        # The rotation interval arnika was started with, as configured
        # (ARNIKA_INTERVAL, e.g. "30s"). The Overview used to print "30 s" as a
        # literal; this is the value compose actually passed. None when unset,
        # which the page renders as "not reported" rather than a default.
        "arnika_interval": os.environ.get("ARNIKA_INTERVAL") or None,
    }


# Services that exist only in a compose OVERLAY behind a profile, mapped to the
# profile that enables them. Absent is the correct state for these whenever the
# profile is not active, and the base `docker-compose.yml` does not define them
# at all -- so on a healthy default stack three of the ten rows below are
# absent BY DESIGN.
#
# Without this table `/api/stack` reported `absent` for "you did not start the
# crossvalidate overlay" and for "bb84-kme-a died" using the same word, and the
# Overview page painted both the same grey. Three rows therefore read as
# failures on a stack with nothing wrong with it, which is exactly the
# absence-rendered-as-a-measurement defect this project treats as a bug
# everywhere else.
#
# Derived from the compose files rather than asserted here. This comment used to
# say the values were already checked by tests/test_optional_services_are_labelled.py
# when no such file existed, so nothing did. It exists now: it reads every
# compose file at the repository root and fails if a profile-gated service is
# missing here, or if an entry names the wrong profile or file.
PROFILE_GATED: dict[str, tuple[str, str]] = {
    "qkdnetsim-kme": ("crossvalidate", "docker-compose.qkdnetsim.yml"),
    "alice-ipsec": ("ipsec", "docker-compose.strongswan.yml"),
    "bob-ipsec": ("ipsec", "docker-compose.strongswan.yml"),
}


# `/` polls this every 3 s from every open tab. The handler was `async def` while
# calling the blocking Docker SDK, so each poll stalled the event loop that also
# serves every other route -- the same defect `/api/vpn/protocols` already fixed
# with a plain `def` and a short cache. Plain `def` lets FastAPI run it in its
# threadpool; the cache means N viewers cost one Docker round-trip per window.
STACK_TTL_S = float(os.environ.get("STACK_TTL_S", "3.0"))


@app.get("/api/stack")
def stack() -> list[dict[str, Any]]:
    """Container status for the main services.

    `absent` means the container is not present. For a profile-gated service
    that is the expected state unless its overlay was started, so those rows
    carry `optional: true` plus the profile and compose file that would create
    them. A consumer that ignores the flag renders exactly what it did before.
    """
    hit, _ = _cached("stack", STACK_TTL_S)
    if hit is not None:
        return hit
    return _store("stack", _stack_uncached())


# The containers /api/stack reports on, in display order.
STACK_SERVICES: tuple[str, ...] = (
    "alice", "bob", "bb84-kme-a", "bb84-kme-b", "webui-backend",
    "webui-frontend", "pqc-validator", "alice-ipsec", "bob-ipsec",
    "qkdnetsim-kme",
)


def _stack_uncached() -> list[dict[str, Any]]:
    names = STACK_SERVICES

    def gating(n: str, status: str) -> dict[str, Any]:
        """Why this row may legitimately be absent. Empty for required ones.

        The explanation of absence is attached only to an absent row. It used
        to ride on every optional row, so a green `running` chip for
        alice-ipsec carried the tooltip "Absent here means the overlay was not
        started" -- a note contradicting the chip it was attached to.
        """
        if n not in PROFILE_GATED:
            return {}
        profile, compose = PROFILE_GATED[n]
        where = (f"not in the default stack: defined only in {compose} behind "
                 f"`profiles: [\"{profile}\"]`.")
        if status == "absent":
            note = (f"{where} Absent here means the overlay was not started on "
                    f"this host, not that anything failed.")
        else:
            note = where
        return {
            "optional": True,
            "profile": profile,
            "compose_file": compose,
            "note": note,
        }

    out: list[dict[str, Any]] = []
    cli = app.state.docker
    if cli is None:
        # `unknown`, not `absent`: we could not look. Keep the gating metadata
        # so the page can still explain the optional rows.
        return [{"name": n, "status": "unknown", **gating(n, "unknown")} for n in names]
    for n in names:
        try:
            c = cli.containers.get(n)
        except docker.errors.NotFound:
            # The container genuinely is not there: Docker answered 404 for
            # the name. This is the only path that may say "absent".
            out.append({"name": n, "status": "absent", **gating(n, "absent")})
            continue
        except Exception as e:
            # Anything else -- an APIError, a socket timeout, a daemon that is
            # restarting -- means we could not look, which is not the same
            # fact as "not there". This branch used to share the absent one
            # (`except Exception:`), so a transient Docker error painted
            # bb84-kme-a as missing, and qkdnetsim-kme as absent "not that
            # anything failed" when something had.
            log.warning("docker lookup of %s failed: %s", n, e)
            out.append({"name": n, "status": "unknown", "error": str(e)[:ERROR_TEXT_MAX_CHARS],
                        **gating(n, "unknown")})
            continue

        # Reading the image is a SEPARATE failure from the container being
        # absent, and it used to be inside the same try. `c.image` raises
        # ImageNotFound whenever the image the container runs has lost its
        # tag -- which happens routinely: rebuilding `pqcqkd/node-alice:local`
        # leaves every other container still running the previous, now
        # dangling, image ID.
        #
        # Measured on the deployed host: after rebuilding alice, `bob` was
        # `Up 4 days` and rotating keys normally, `containers.get("bob")`
        # returned status=running, and `bob.image` raised
        # `ImageNotFound: 404 ... /images/1a2e95e58251`. The Overview page
        # showed bob as ABSENT for a container that was working.
        #
        # A cosmetic field must not be able to erase an observed status.
        image = ""
        try:
            tags = c.image.tags
            image = tags[0] if tags else ""
        except Exception:
            # Untagged is a real, reportable state -- not an empty string,
            # which would read as "no image information available".
            image = "<untagged>"

        out.append({
            "name": n,
            "status": c.status,
            "image": image,
            "started_at": c.attrs.get("State", {}).get("StartedAt"),
            **gating(n, c.status),
        })
    return out


# ----------------------- Stats -----------------------
# /benchmarks polls this once a second per open tab (usePoll(..., 1000)), and
# each poll was two KME round trips. One second of cache collapses any number
# of viewers onto one sample per second without making the chart visibly
# staler than its own poll interval.
STATS_TTL_S = float(os.environ.get("STATS_TTL_S", "1.0"))


@app.get("/api/stats")
async def stats():
    hit, _ = _cached("stats", STATS_TTL_S)
    if hit is not None:
        return hit
    async with httpx.AsyncClient(timeout=2.0) as client:
        results: dict[str, Any] = {}
        for label, url in (("alice", KME_A_URL), ("bob", KME_B_URL)):
            try:
                r = await client.get(f"{url}/sim/stats")
                # A KME that answers 4xx/5xx has not reported stats. Its
                # FastAPI error body `{"detail": ...}` used to be passed on as
                # though it were the stats object.
                if r.status_code >= 400:
                    results[label] = {"error": f"HTTP {r.status_code}: {r.text[:ERROR_TEXT_MAX_CHARS]}"}
                else:
                    results[label] = r.json()
            except Exception as e:
                results[label] = {"error": str(e)}
        return _store("stats", results)


# ----------------------- Log redaction and bounds -----------------------
# `GET /api/logs/{name}` served ARNIKA_PSK to anyone who asked. The arnika pin
# before release 0.2.0 (3a8cc13) printed its whole configuration at startup,
# including `Arnika PSK: <value>` verbatim (its config/config.go:78), and the
# route had no tail cap, so a large enough `?tail=` reached back past the
# 129,319 lines alice had logged to the banner. Measured on the public demo on
# 2026-09-25 by value LENGTH only (44 characters, a base64 32-byte key); the
# value itself was never printed.
#
# The current pin (f4cf9ba, the head of the still-open arnika PR #51) prints
# the same label with redactSecret()'s `(set, N bytes)` instead of the value
# (config/config.go:119 and :168-173 there). The banner rule below still
# matches that line and replaces an already-redacted value, which costs only
# the byte count. It stays because the label is all this rule can see: a node
# rolled back to 3a8cc13 writes the same label with the key after it, and the
# PR head is not yet a merge commit.
#
# The same missing cap let one request make the backend serialise alice-ipsec's
# 3.4 million log lines.
#
# Two rules, because they guard different things:
#   1. the arnika banner line is redacted whatever its value looks like -- a
#      short test PSK is still the PSK;
#   2. elsewhere, a key-ish label followed by something shaped like key material
#      (24+ base64/hex characters) is redacted. The length floor is what keeps
#      "failed to configure random PSK: <error text>" readable on /console.
# See tests/test_logs_endpoint_redacts_secrets.py.
LOGS_MAX_TAIL = int(os.environ.get("LOGS_MAX_TAIL", "2000"))
LOGS_TTL_S = float(os.environ.get("LOGS_TTL_S", "1.5"))
_ARNIKA_PSK_LINE = re.compile(r"(?im)^(.*?\bArnika PSK:[ \t]*)(\S.*)$")
_KEYISH_VALUE = re.compile(
    r"(?i)(\b(?:preshared key|private key|psk|secret)[ \t]*[:=][ \t]*)"
    r"([A-Za-z0-9+/_-]{24,}={0,2})"
)
_REDACTED = "(redacted)"


def _redact_log(text: str) -> tuple[str, int]:
    """Remove key material from container or service logs.

    Returns the redacted text and how many substitutions were made, so a caller
    can report that something was withheld rather than silently shortening it.
    """
    text, n1 = _ARNIKA_PSK_LINE.subn(lambda m: m.group(1) + _REDACTED, text)
    text, n2 = _KEYISH_VALUE.subn(lambda m: m.group(1) + _REDACTED, text)
    return text, n1 + n2


# ----------------------- Phase 12-A: file-backed log endpoints -----------------------
# Registered BEFORE the dynamic /api/logs/{name} route so "files" and
# "download/<svc>" are matched literally first.
@app.get("/api/logs/files")
async def list_log_files() -> dict[str, list]:
    """List every *.log* file present in the shared LOG_DIR volume."""
    return {"files": logging_setup.list_log_files()}


@app.get("/api/logs/download/{service}")
def download_log(service: str, lines: int = Query(1000, ge=1, le=LOGS_MAX_TAIL)):
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
    # Redacted here too. Only the Python services write these files and none of
    # them logs key material today, but "today" is not a property a download
    # route should rely on; the container-log route below (Docker's stdout and
    # stderr) is where arnika's startup banner leaked.
    text, _ = _redact_log(logging_setup.read_tail(safe, lines=int(lines)))
    return PlainTextResponse(
        text,
        headers={"Content-Disposition": f'attachment; filename="{safe}.log"'},
    )


# ----------------------- Phase 13: Backend-stored exports -----------------------
# Persist artefacts (PNG, JSON, CSV, GIF, log) into a shared volume, then offer
# them for download via a stable URL. Lets users save/share simulation outputs
# beyond a single browser session.
#
# The store is public: anyone who can reach the host can list, download and
# delete what is in it. So its bounds are set HERE, whatever DEMO_MODE says.
# They used to be tightened only by deploy/docker-compose.demo.yml, and the
# public host does not run that overlay, so it ran on the looser defaults
# (50 MiB x 200 files, roughly 10 GB of disk reachable by anonymous POSTs).
_MIB = 1024 * 1024
EXPORT_DIR = os.environ.get("EXPORT_DIR", "/var/lib/pqcqkd-exports")
# Per file and file count: the values the demo overlay already used. The whole
# public store, recordings included, was 12.7 MB on 2026-09-25, well inside one
# file's limit.
EXPORT_MAX_BYTES = int(os.environ.get("EXPORT_MAX_BYTES", 25 * _MIB))
EXPORT_MAX_FILES = int(os.environ.get("EXPORT_MAX_FILES", 100))
# The whole store. Count x size alone still allowed 2.5 GB; this caps the disk
# the catalogue can occupy. The public store held 60 files / 12.7 MB on
# 2026-09-25, so this is ample headroom for real use.
EXPORT_MAX_TOTAL_BYTES = int(os.environ.get("EXPORT_MAX_TOTAL_BYTES", 512 * _MIB))
# What the frontend actually saves (exporters.ts: json, csv, png, gif, webm),
# plus the two plain-text forms the download route already typed. Anything
# else was accepted verbatim before, which made the store a public file drop.
EXPORT_CONTENT_TYPES: dict[str, str] = {
    "json": "application/json",
    "csv": "text/csv",
    "png": "image/png",
    "gif": "image/gif",
    "webm": "video/webm",
    "log": "text/plain",
    "txt": "text/plain",
}


def _ensure_export_dir():
    from pathlib import Path
    d = Path(EXPORT_DIR)
    d.mkdir(parents=True, exist_ok=True)
    return d


def _gc_export_dir() -> None:
    """Keep the store inside EXPORT_MAX_FILES and EXPORT_MAX_TOTAL_BYTES.

    The newest files are kept for as long as both bounds hold; from the first
    file that would break either, it and everything older is deleted.
    """
    from pathlib import Path
    d = Path(EXPORT_DIR)
    if not d.exists():
        return
    files = sorted(d.glob("*"), key=lambda p: p.stat().st_mtime, reverse=True)
    kept_files, kept_bytes, full = 0, 0, False
    for f in files:
        try:
            size = f.stat().st_size
        except FileNotFoundError:
            continue
        full = full or (kept_files + 1 > EXPORT_MAX_FILES
                        or kept_bytes + size > EXPORT_MAX_TOTAL_BYTES)
        if not full:
            kept_files += 1
            kept_bytes += size
            continue
        try: f.unlink()
        except Exception: pass


# Plain `def`: decoding and writing up to EXPORT_MAX_BYTES is blocking work, and
# under `async def` it ran on the event loop that serves every other route.
@app.post("/api/exports/save")
def export_save(req: dict):
    """Body: {name: str, ext: str, content_b64: str}
    Saves <timestamp>-<safe_name>.<ext> into EXPORT_DIR.  Returns the URL.
    Bounded in code, not by DEMO_MODE: EXPORT_CONTENT_TYPES extensions only
    (415 otherwise), EXPORT_MAX_BYTES per file, and EXPORT_MAX_FILES /
    EXPORT_MAX_TOTAL_BYTES for the store, oldest evicted first. Names are
    sanitised (no path traversal), and POSTs are rate-limited."""
    import base64
    import re
    import time
    raw_name = str(req.get("name", "export"))
    ext = str(req.get("ext", "")).lstrip(".").lower()
    content_b64 = req.get("content_b64")
    if not content_b64:
        raise HTTPException(400, "content_b64 required")
    safe_ext = re.sub(r"[^A-Za-z0-9]+", "", ext)[:8]
    if safe_ext not in EXPORT_CONTENT_TYPES:
        # Checked before decoding, so a refused upload costs no base64 work.
        raise HTTPException(
            415, f"extension {safe_ext or '(none)'!r} not accepted; "
                 f"allowed: {sorted(EXPORT_CONTENT_TYPES)}")
    try:
        data = base64.b64decode(content_b64, validate=False)
    except Exception as e:
        raise HTTPException(400, f"invalid base64: {e}")
    # The store cap as well: a file larger than the whole store would be
    # evicted by _gc_export_dir the moment it landed, and the URL returned
    # below would name a file that no longer exists.
    limit = min(EXPORT_MAX_BYTES, EXPORT_MAX_TOTAL_BYTES)
    if len(data) > limit:
        raise HTTPException(413, f"payload {len(data)} > limit {limit}")

    safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "-", raw_name)[:80] or "export"
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
    # Same table the save route admits by. Files written before the allow-list
    # existed can carry any extension; those are served as opaque bytes.
    media_type = EXPORT_CONTENT_TYPES.get(p.suffix.lower().lstrip("."),
                                          "application/octet-stream")
    return FileResponse(p, media_type=media_type, filename=safe)


@app.delete("/api/exports/{filename}")
async def export_delete(filename: str):
    import re
    from pathlib import Path
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", filename)[:120]
    if safe != filename or ".." in safe:
        raise HTTPException(400, "invalid filename")
    p = Path(EXPORT_DIR) / safe
    # 404 for a file that is not there. This answered {"ok": true} either way,
    # so a delete that removed nothing -- a typo, or a file another visitor had
    # already deleted -- read as a successful deletion.
    try:
        p.unlink()
    except FileNotFoundError:
        raise HTTPException(404, "not found")
    return {"ok": True}


# ----------------------- Logs (container stdout and stderr, allow-listed by name) -----------------------
# The containers a public route may reach through the Docker socket, and the
# only ones. ONE table for both routes that take a container name from the URL,
# so they cannot drift apart.
#
# `/api/logs/{name}` used to call `cli.containers.get(name)` for ANY name. On
# the public demo that served the log of every container on the host --
# measured 2026-09-25: `/api/logs/caddy` answered 200 with the reverse proxy's
# access log, visitor IPs and User-Agents included. `/api/wg/{node}` ran
# `docker exec wg show wg0` in any container named in the path, including
# webui-frontend. The download route beside them was already allow-listed.
#
# WG_NODES: the two containers that own the WireGuard lane's interfaces (wg0
# and wg1).
# LOG_CONTAINERS: what /console tails (Console.tsx NAMES, same order).
WG_NODES: tuple[str, ...] = ("alice", "bob")
LOG_CONTAINERS: tuple[str, ...] = WG_NODES + (
    "bb84-kme-a", "bb84-kme-b", "alice-ipsec", "bob-ipsec",
)


def _require_known_container(name: str, allowed: tuple[str, ...]) -> None:
    """404 for a name outside `allowed`, before Docker or the cache is touched.

    404 rather than 403: from outside, a container this route will not serve
    and a container that does not exist are the same answer, and saying which
    one it is would itself be a probe of the host.
    """
    if name not in allowed:
        raise HTTPException(404, f"unknown container {name!r}; allowed: {list(allowed)}")


def _prune_expired(prefix: str, ttl: float) -> None:
    """Drop cache entries under `prefix` older than `ttl`.

    The log cache is keyed per (name, tail), and `tail` ranges over
    1..LOGS_MAX_TAIL, so without pruning the entries of a sweep over `tail`
    would stay in memory for the life of the process, each holding up to
    LOGS_MAX_TAIL lines.
    """
    now = time.monotonic()
    # `list(...)` first: this runs in the threadpool while other handlers write
    # the same dict, and iterating a dict that changes size raises. Copying
    # the items is a single C call, so no other thread can interleave with it.
    for k, v in list(_pure_cache.items()):
        if k.startswith(prefix) and now - v["at"] >= ttl:
            _pure_cache.pop(k, None)


@app.get("/api/logs/{name}")
def logs(name: str, tail: int = Query(200, ge=1, le=LOGS_MAX_TAIL)) -> dict[str, Any]:
    """Container stdout and stderr, redacted and bounded (see _redact_log).

    Both streams, because docker-py's `logs()` returns both unless told
    otherwise, and the call below relies on that default. It matters for
    arnika: at the current pin (f4cf9ba) it writes every record to stderr
    through its slog handler (logging.go:42 and :63 there), so a stdout-only
    read would show no arnika line at all.

    Only for LOG_CONTAINERS; any other name is 404 before Docker is asked.

    Plain `def`: the Docker SDK blocks, and /console polls this every 1.5 s.
    """
    _require_known_container(name, LOG_CONTAINERS)
    key = f"logs:{name}:{tail}"
    hit, _ = _cached(key, LOGS_TTL_S)
    if hit is not None:
        return hit
    _prune_expired("logs:", LOGS_TTL_S)
    cli = app.state.docker
    if cli is None:
        raise HTTPException(503, "docker not available")
    try:
        c = cli.containers.get(name)
        data = c.logs(tail=tail).decode("utf-8", errors="replace")
    except Exception as e:
        raise HTTPException(404, str(e))
    text, n = _redact_log(data)
    return _store(key, {"name": name, "log": text, "redacted": n})


# ----------------------- WireGuard show -----------------------
# `wg show <if> dump` PRINTS SECRETS. From wg(8): the first line is
# "private-key, public-key, listen-port, fwmark" tab-separated, and each peer
# line is "public-key, preshared-key, endpoint, allowed-ips, latest-handshake,
# rx, tx, keepalive". Fields 1 and 2 respectively are the interface private key
# and the preshared key, both in plaintext base64.
#
# This route served that verbatim, unauthenticated, with no DEMO_MODE gate. A
# 2026-08-27 GET of the public demo's /api/wg/alice returned alice's wg0 private
# key and the live preshared key -- and on this stack the wg0 preshared key is
# the arnika HKDF(QKD || PQC) output, i.e. the entire product of the key path
# the project exists to demonstrate. Nothing in the frontend has ever called
# this route, so the exposure carried no compensating benefit.
#
# The non-dump form is what wireguard-tools redacts for you: it prints
# "private key: (hidden)" and "preshared key: (hidden)". Use it. Then redact
# again on the way out, so that editing one word of the command back is not by
# itself sufficient to leak. See tests/test_wg_endpoint_redacts_secrets.py.
#
# Two interfaces per node since release 0.2.0, the layering of arXiv:2604.05599:
#   wg0  the hop tunnel. arnika writes its preshared key: HKDF-SHA3-256 over
#        the QKD key and a PQC-HPKE key that arnika agrees with its peer.
#   wg1  the end-to-end data tunnel. Its peer endpoint is the peer's wg0
#        address, so wg1 packets travel inside wg0. Rosenpass writes its
#        preshared key through Rosenpass's own WireGuard output, and the
#        Rosenpass exchange itself runs over wg0.
# Both commands are the non-dump form, for the reason above; wg1's preshared
# key is as secret as wg0's.
WG_SHOW_CMD = "wg show wg0"
WG_DATA_SHOW_CMD = "wg show wg1"

# Which process writes each interface's preshared key. This is the deployed
# CONFIGURATION (docker-compose.yml and nodes/alice/entrypoint.sh), stated per
# interface so a reader of the API does not have to infer it. It is not a
# measurement: `wg show` prints only whether SOME preshared key is set (the
# `preshared key: (hidden)` line), never who set it -- and since release 0.2.0
# the entrypoint sets a random `wg genpsk` placeholder on every peer at
# creation, so the line is there before either keying daemon has written
# anything. What shows that the configured writer has keyed an interface is a
# completed handshake: see _WG_PSK_RE.
WG_PSK_SOURCE: dict[str, str] = {
    "wg0": "arnika: HKDF-SHA3-256(QKD || PQC-HPKE)",
    "wg1": "rosenpass",
}

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


def _wg_show_one(container, node: str, iface: str, cmd: str) -> dict[str, Any]:
    """One interface's redacted `wg show`, with the fields every caller gets.

    `error` is None when the command ran. A non-zero `rc` is not an error in
    this sense: `wg show wg1` on a node without wg1 exits 1 with "Unable to
    access interface", and that text is the honest answer, so it is returned.
    """
    rc, out = container.exec_run(cmd)
    return {
        "node": node,
        "interface": iface,
        "rc": rc,
        "output": _redact_wg(out.decode("utf-8", errors="replace")),
        "psk_source": WG_PSK_SOURCE[iface],
        "error": None,
    }


# Per-node cache for `GET /api/wg/{node}`. Since release 0.2.0 a sample is two
# `docker exec`s (wg0 and wg1), on a public, unauthenticated GET that the rate
# limiter does not cover (it meters only the mutating verbs), so without a
# cache every anonymous request cost the host two execs. With it, a node costs
# at most two execs per WG_SHOW_TTL_S whatever the request rate. The default
# matches VPN_SAMPLE_TTL_S, the same kind of `wg show` snapshot. Keys are
# `wg:<node>` for WG_NODES only (the allow-list runs first), so the cache holds
# at most len(WG_NODES) entries and needs no pruning.
#
# A 404 is cached too, as /api/vpn/protocols caches its failure shapes: a node
# whose exec fails must not be the case that costs an exec on every request.
WG_SHOW_TTL_S = float(os.environ.get("WG_SHOW_TTL_S", "5.0"))


@app.get("/api/wg/{node}")
def wg_show(node: str) -> dict[str, Any]:
    """wg0 at the top level, as before, and wg1 under `data_tunnel`.

    The top-level fields keep what they always meant (wg0), so an existing
    reader is unaffected; wg1 is additive. Both carry the same keys, and the
    top level adds when the pair was sampled (`observed_at`) and for how long
    it is served from the cache (`cache_ttl_s`), so a cached answer can be
    told from a fresh one.

    Plain `def`: two blocking `docker exec`s, which under `async def` would run
    on the event loop and stall every other request for their duration.
    """
    # alice and bob only (WG_NODES): the route used to exec in whatever
    # container the path named.
    _require_known_container(node, WG_NODES)
    key = f"wg:{node}"
    hit, _ = _cached(key, WG_SHOW_TTL_S)
    if hit is not None:
        if "not_found" in hit:
            raise HTTPException(404, hit["not_found"])
        return hit
    cli = app.state.docker
    if cli is None:
        raise HTTPException(503, "docker not available")
    try:
        c = cli.containers.get(node)
        hop = _wg_show_one(c, node, "wg0", WG_SHOW_CMD)
    except Exception as e:
        # Bounded like every other exception text this module puts in a
        # response, and bounded before it is cached, so the cached 404 and the
        # first one carry the same detail.
        detail = str(e)[:ERROR_TEXT_MAX_CHARS]
        _store(key, {"not_found": detail})
        raise HTTPException(404, detail)
    # wg0 answered, so the container exists. A failure now is about wg1 alone
    # and must not turn a wg0 reading into a 404: it is reported in place, with
    # no rc and no output rather than invented ones.
    try:
        data = _wg_show_one(c, node, "wg1", WG_DATA_SHOW_CMD)
    except Exception as e:
        log.warning("wg show wg1 failed in %s: %s", node, e)
        data = {"node": node, "interface": "wg1", "rc": None, "output": None,
                "psk_source": WG_PSK_SOURCE["wg1"], "error": str(e)[:ERROR_TEXT_MAX_CHARS]}
    return _store(key, {**hop, "data_tunnel": data,
                        "observed_at": time.time(), "cache_ttl_s": WG_SHOW_TTL_S})


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


# ----------------------- Upstream bodies -----------------------
def _upstream_json(r: Any, source: str) -> Any:
    """The JSON body of an upstream 2xx answer, or an HTTPException.

    Several proxies below returned `r.json()` without looking at the status, so
    an upstream 4xx/5xx -- whose FastAPI body `{"detail": ...}` is valid JSON --
    went out as HTTP 200 and was rendered, or cached, as data. The upstream
    status is passed through, as `/api/pqc/interop` already did.
    """
    if r.status_code >= 400:
        raise HTTPException(
            r.status_code, f"{source} answered HTTP {r.status_code}: {r.text[:ERROR_TEXT_MAX_CHARS]}")
    try:
        return r.json()
    except ValueError as e:
        raise HTTPException(502, f"{source} answered with a body that is not JSON: {e}")


# ----------------------- Physics params (proxy to KME A) -----------------------
@app.get("/api/sim/params")
async def sim_params_proxy():
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            r = await client.get(f"{KME_A_URL}/sim/params")
    except httpx.HTTPError as e:
        raise HTTPException(503, f"kme unavailable: {e}")
    return _upstream_json(r, "kme")


# ----------------------- Simulator control fan-out -----------------------
# These three endpoints POST to BOTH KMEs. Each used to wrap the call in
# `try/except Exception` that logged and continued, then `return {"ok": True}`
# unconditionally -- so with neither KME reachable the caller got HTTP 200 and
# `{"ok": true}`, and /physics printed "Reverted to config/qkd_params.yaml
# defaults." having changed nothing anywhere.
#
# Same family as the restart button that always 403'd: an action that reports
# success it did not have. There the promise was discarded; here the success was
# fabricated one layer earlier.
#
# `ok` now means EVERY peer was reached and answered. `nodes` says which did, so
# a half-applied override -- alice updated, bob not -- is visible rather than
# indistinguishable from both succeeding. That asymmetry matters here: the two
# KMEs must agree on the physics or the key rates they report diverge for a
# reason nobody can see.
def _fanout_result(outcomes: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Build the response, and say plainly which peers answered.

    A peer is `ok` only if the POST completed AND the KME did not answer 4xx/5xx.
    """
    reached = [n for n, o in outcomes.items() if o["ok"]]
    return {
        "ok": len(reached) == len(outcomes),
        "reached": len(reached),
        "of": len(outcomes),
        # Bodies are dropped here: `nodes` answers "did this peer apply it",
        # and the applied values are returned once, under `kme`.
        "nodes": {n: {k: v for k, v in o.items() if k != "body"}
                  for n, o in outcomes.items()},
    }


async def _post_both(client: httpx.AsyncClient, path: str,
                     json: dict[str, Any] | None = None) -> dict[str, dict[str, Any]]:
    """POST `path` to both KMEs, recording each outcome instead of discarding it."""
    outcomes: dict[str, dict[str, Any]] = {}
    for name, url in (("alice", KME_A_URL), ("bob", KME_B_URL)):
        try:
            r = await client.post(f"{url}{path}", json=json) if json is not None \
                else await client.post(f"{url}{path}")
            if r.status_code >= 400:
                outcomes[name] = {"ok": False, "status": r.status_code,
                                  "error": r.text[:ERROR_TEXT_MAX_CHARS], "body": None}
            else:
                # Body captured HERE. A first draft of this had the caller POST
                # a second time to read it, which applies the override twice --
                # a fix that introduces a worse bug than the one it closes.
                try:
                    body = r.json()
                except Exception:
                    body = None
                outcomes[name] = {"ok": True, "status": r.status_code, "body": body}
        except Exception as e:
            # Logged AND reported. Logging alone is what made this invisible:
            # the operator never sees the backend's log.
            log.warning("%s on %s failed: %s", path, url, e)
            outcomes[name] = {"ok": False, "status": None,
                              "error": str(e)[:ERROR_TEXT_MAX_CHARS], "body": None}
    return outcomes


def _raise_unless_every_peer_applied(outcomes: dict[str, dict[str, Any]],
                                     action: str) -> None:
    """Raise unless every KME applied the change, naming what each peer did.

    Used by the backend switch only. A KME that refused (4xx/5xx) makes the
    route answer with that status; a KME that could not be reached, with 502.
    Wrapping either in HTTP 200 is how /physics came to print "Backend switch
    to qkdnetsim_proxy requested." while both KMEs had answered 503.

    Stricter than the parameter routes, which report an unreachable peer
    in-band (`ok: false`): a switch that reached one KME leaves the two on
    different backends, and no reader of a 200 should have to look inside the
    body to learn that.

    The detail is a string, not the per-node dict: the frontend renders
    `body.detail` into a sentence. Every peer is named in it, so a half-applied
    change (alice took it, bob did not) is still visible.
    """
    if all(o["ok"] for o in outcomes.values()):
        return
    refused = [o["status"] for o in outcomes.values()
               if o["status"] is not None and o["status"] >= 400]
    parts = []
    for n, o in outcomes.items():
        if o["ok"]:
            parts.append(f"{n}: applied")
        elif o["status"] is None:
            parts.append(f"{n}: unreachable ({o['error']})")
        else:
            parts.append(f"{n}: HTTP {o['status']} {o['error']}")
    raise HTTPException(refused[0] if refused else 502,
                        f"{action} not applied on every KME: " + "; ".join(parts))


@app.post("/api/sim/backend", dependencies=[Depends(_require_live_param_overrides)])
async def sim_backend_proxy(req: dict[str, Any]):
    """Switch the simulator backend on BOTH KMEs. Opt-in; see
    LIVE_PARAM_OVERRIDES_ENABLED.

    Anything short of both KMEs applying it is an HTTP error: the refusing
    KME's status (400 unknown backend, 503 dependency not deployed), or 502 for
    a KME that could not be reached -- see _raise_unless_every_peer_applied.
    """
    async with httpx.AsyncClient(timeout=5.0) as client:
        outcomes = await _post_both(client, "/sim/backend", req)
    # Invalidated before any raise: a half-applied switch has still changed the
    # config of the peer that took it.
    _invalidate_keyrate_cache()
    _raise_unless_every_peer_applied(outcomes, "backend switch")
    return _fanout_result(outcomes)


@app.get("/api/sim/params/editable")
async def sim_params_editable_proxy():
    """Editable parameter descriptors + current effective values (from KME A)."""
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            r = await client.get(f"{KME_A_URL}/sim/params/editable")
    except httpx.HTTPError as e:
        raise HTTPException(503, f"kme unavailable: {e}")
    return _upstream_json(r, "kme")


@app.post("/api/sim/params", dependencies=[Depends(_require_live_param_overrides)])
async def sim_params_set_proxy(req: dict[str, Any]):
    """Apply UI parameter overrides to BOTH KMEs (in-memory; config is default).

    Opt-in; see LIVE_PARAM_OVERRIDES_ENABLED."""
    last: dict[str, Any] | None = None
    async with httpx.AsyncClient(timeout=5.0) as client:
        outcomes = await _post_both(client, "/sim/params", req)
        # A 4xx from a KME is a rejected override -- a validation error the user
        # must see, not a peer being down -- so it still raises rather than
        # being folded into the per-node report.
        for name, o in outcomes.items():
            if o["status"] is not None and o["status"] >= 400:
                raise HTTPException(o["status"], f"{name}: {o['error']}")
        # The applied values, from whichever peer answered -- read from the
        # response already captured, not by POSTing again.
        last = next((o["body"] for o in outcomes.values() if o["ok"] and o["body"]),
                    None)
    _invalidate_keyrate_cache()
    return {**_fanout_result(outcomes), "kme": last}


@app.post("/api/sim/params/reset", dependencies=[Depends(_require_live_param_overrides)])
async def sim_params_reset_proxy():
    """Drop UI overrides on both KMEs — revert to config defaults.

    Gated with the other two: a reset writes to the same shared override set,
    so an open reset would let any visitor wipe overrides someone else set."""
    async with httpx.AsyncClient(timeout=5.0) as client:
        outcomes = await _post_both(client, "/sim/params/reset")
    _invalidate_keyrate_cache()
    return _fanout_result(outcomes)


# `POST /api/sim/optimize` was here. Deleted, not disabled.
#
# It proxied the KME's Bayesian optimiser (skopt gp_minimize, 50 evaluations).
# Measured against the live public demo: 14.6 s of server CPU per request,
# unauthenticated, and the per-IP limiter above was inert because the host runs
# with DEMO_MODE unset. Nothing called it -- a repo-wide grep found only the two
# route definitions and two ARCHITECTURE.md diagram lines -- and /physics does
# its mu/nu optimisation as a client-side grid search (PhysicsParams.tsx).
#
# So: a dead endpoint that was also the cheapest way to exhaust the box.
@app.get("/api/pqc/algorithms")
async def pqc_algos():
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            r = await client.get(f"{PQC_VALIDATOR_URL}/api/algorithms")
    except httpx.HTTPError as e:
        raise HTTPException(503, f"pqc-validator unavailable: {e}")
    return _upstream_json(r, "pqc-validator")


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
    except httpx.HTTPError as e:
        raise HTTPException(503, f"pqc-validator unavailable: {e}")
    # A 400 for an unsupported algorithm is the validator's answer, not a
    # roundtrip result; it used to come back as HTTP 200 `{"detail": ...}`.
    return _upstream_json(r, "pqc-validator")


# Two endpoints that are PURE FUNCTIONS of things that rarely change, and were
# recomputed from scratch on every page load.
#
# Measured 2026-09-26 against the pqc-validator and bb84-kme images run on a
# development workstation, uncached (a small hosted VM is slower):
#
#     POST /api/pqc/agility    1.7 s      -- 3 ML-KEM + 3 HQC keygen/encap/decap
#                                            and 3 ML-DSA + 4 SLH-DSA keygen/
#                                            sign/verify/reject-tampered in
#                                            liboqs, median of six calls; the
#                                            three SLH-DSA "s" sets are about
#                                            1.6 s of it
#     GET  /api/verify/keyrate 1.0 s      -- closed form (microseconds) plus a
#                                            scipy optimise in the TNO engine;
#                                            first call, then 0.2 s once the
#                                            engine is imported
#
# /verify fetches both on mount, so uncached, every visitor costs the sum of
# the two in server CPU before seeing anything. The agility matrix does not
# depend on the request at all -- it runs a fixed algorithm list -- and the
# key-rate cross-check depends only on config, which POST /api/sim/params
# changes.
#
# CACHED RATHER THAN MOVED TO THE BROWSER, deliberately. `lib/sim/pqc.ts` has an
# `agilityMatrix()` that computes the same matrix with @noble/post-quantum, and
# /verify runs it only as an on-demand cross-check BESIDE the liboqs rows
# (`lib/sim/agilityCrossCheck.ts`). Using it as a replacement would be the
# bigger saving -- and would make the panel title ("Crypto-Agility Matrix
# (liboqs ...)") and the citable export line ("# Crypto-agility matrix
# (liboqs)") FALSE, because the numbers would then come from a different
# library. Provenance is the point of that page. A cache buys most of the time
# back and costs no honesty.
#
# Failures are cached too, briefly, under their own key and TTL: an unreachable
# or failing validator should not mean a 20-second httpx timeout per viewer.
# The upstream status is read before anything is cached, so a validator's 4xx or
# 5xx body is never stored as the matrix.
PQC_AGILITY_TTL_S = float(os.environ.get("PQC_AGILITY_TTL_S", "300.0"))
PQC_AGILITY_ERROR_TTL_S = float(os.environ.get("PQC_AGILITY_ERROR_TTL_S", "10.0"))
KEYRATE_TTL_S = float(os.environ.get("KEYRATE_TTL_S", "10.0"))
_pure_cache: dict[str, dict[str, Any]] = {}


def _cached(key: str, ttl: float):
    hit = _pure_cache.get(key)
    if hit is not None and (time.monotonic() - hit["at"]) < ttl:
        return hit["value"], hit["at"]
    return None, None


def _store(key: str, value: Any) -> Any:
    _pure_cache[key] = {"at": time.monotonic(), "value": value}
    return value


def _invalidate_keyrate_cache() -> None:
    """Drop the key-rate cache whenever the KME's effective config changes.

    A bare TTL would make VERIFICATION_CHECKLIST.md row 4.7.10 racy: it tells
    the reader to POST a new link length and reload /verify, and within the
    window they would read the previous distance's verdict and conclude the
    endpoint is broken. Explicit invalidation keeps the checklist executable as
    written.

    Called from the three proxies that mutate KME state -- backend swap,
    parameter override, override reset. Defined here rather than beside them so
    it sits with the cache it clears; Python resolves the global at call time,
    so the ordering is irrelevant at runtime.
    """
    _pure_cache.pop("keyrate", None)


# The request body `/api/pqc/agility` accepts: an optional list of names per
# family, keyed as the validator keys them, mapped to the `family` value its
# matrix rows carry.
AGILITY_REQUEST_FAMILIES: dict[str, str] = {"kems": "KEM", "sigs": "SIG"}


def _agility_request(req: dict[str, Any] | None) -> dict[str, list[str]] | None:
    """The per-family name lists a caller asked for, or None for the default.

    Shape only; which names are acceptable is decided against the default
    matrix in _select_agility_rows. An empty or missing list means "that whole
    family", as it does in the validator.
    """
    if not req:
        return None
    unknown = sorted(set(req) - set(AGILITY_REQUEST_FAMILIES))
    if unknown:
        raise HTTPException(422, f"unknown field(s) {unknown}; accepted: "
                                 f"{sorted(AGILITY_REQUEST_FAMILIES)}")
    wanted: dict[str, list[str]] = {}
    for key in AGILITY_REQUEST_FAMILIES:
        names = req.get(key)
        if names is None or names == []:
            continue
        if not isinstance(names, list) or not all(isinstance(n, str) for n in names):
            raise HTTPException(422, f"{key} must be a list of algorithm names")
        wanted[key] = names
    return wanted or None


def _select_agility_rows(out: dict[str, Any],
                         wanted: dict[str, list[str]]) -> dict[str, Any]:
    """Answer an explicit request from the default matrix, by selecting rows.

    The allow-list is the default matrix itself -- the validator's own default
    lists, as it reported them -- so there is one list of acceptable names and
    it lives in services/pqc-validator. A list longer than the family is 422
    before its names are read; a name outside the family is 422; repeats are
    dropped, first occurrence kept.

    Every row is computed independently of the others, so a selected row is the
    row the validator would return for that name alone. What a selection can no
    longer do is make the validator run something new, which is what made this
    route expensive: an unbounded list forwarded verbatim costs about 0.6 s of
    validator CPU per SLH-DSA entry, and one request could hold a threadpool
    worker for hours.
    """
    matrix = out.get("matrix") or []
    selected: list[dict[str, Any]] = []
    for key, family in AGILITY_REQUEST_FAMILIES.items():
        available = {r["algo"]: r for r in matrix if r.get("family") == family}
        names = wanted.get(key)
        if names is None:
            selected.extend(available.values())
            continue
        if len(names) > len(available):
            raise HTTPException(
                422, f"{key}: {len(names)} names requested; at most "
                     f"{len(available)} ({list(available)})")
        outside = [n for n in names if n not in available]
        if outside:
            raise HTTPException(
                422, f"{key}: {outside} not in the matrix; accepted: {list(available)}")
        selected.extend(available[n] for n in dict.fromkeys(names))
    passed = sum(1 for r in selected if r.get("ok"))
    return {
        **out,
        "matrix": selected,
        "summary": {"total": len(selected), "passed": passed,
                    "all_pass": passed == len(selected)},
    }


async def _fetch_default_agility() -> dict[str, Any]:
    """Run the validator's default matrix. Raises HTTPException on any failure."""
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            r = await client.post(f"{PQC_VALIDATOR_URL}/api/agility", json={})
    except httpx.HTTPError as e:
        raise HTTPException(503, f"pqc-validator unavailable: {e}")
    out = _upstream_json(r, "pqc-validator")
    if not isinstance(out, dict) or not isinstance(out.get("matrix"), list):
        raise HTTPException(502, "pqc-validator answered without a `matrix` list")
    return out


@app.post("/api/pqc/agility")
async def pqc_agility(req: dict[str, Any] | None = None):
    """Crypto-agility matrix (ML-KEM, HQC, ML-DSA and SLH-DSA across levels).

    The validator is only ever asked for its DEFAULT matrix, and that answer is
    cached. A body naming `kems` and/or `sigs` is served by selecting rows from
    it (_select_agility_rows) rather than forwarded. /verify posts no body.
    """
    wanted = _agility_request(req)
    value, at = _cached("agility", PQC_AGILITY_TTL_S)
    if value is not None:
        out = {**value, "cached": True,
               "cache_age_s": round(time.monotonic() - at, 3)}
    else:
        failed, _ = _cached("agility:error", PQC_AGILITY_ERROR_TTL_S)
        if failed is not None:
            raise HTTPException(failed["status"], failed["detail"])
        try:
            fresh = await _fetch_default_agility()
        except HTTPException as e:
            # Stored under its own key, so a failure never stands in for the
            # matrix and expires on its own, shorter clock.
            _store("agility:error", {"status": e.status_code, "detail": e.detail})
            raise
        _store("agility", fresh)
        out = {**fresh, "cached": False}
    return out if wanted is None else _select_agility_rows(out, wanted)


# ----------------------- Implementation verification -----------------------
@app.get("/api/verify/keyrate")
async def verify_keyrate():
    """TNO-vs-closed-form key-rate cross-check (from KME A).

    Cached for a short TTL. It is a pure function of the KME's effective
    config, which only POST /api/sim/params changes -- and the TTL is short
    enough (10 s) that an operator editing a parameter sees the new figure
    within one poll rather than having to know a cache exists.
    """
    value, at = _cached("keyrate", KEYRATE_TTL_S)
    if value is not None:
        return {**value, "cached": True,
                "cache_age_s": round(time.monotonic() - at, 3)}
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            r = await client.get(f"{KME_A_URL}/sim/keyrate/crosscheck")
    except httpx.HTTPError as e:
        raise HTTPException(503, f"kme unavailable: {e}")
    # Status first. `isinstance(out, dict)` was the only gate, and a FastAPI
    # error body is a dict, so a KME 5xx was cached as the cross-check result.
    out = _upstream_json(r, "kme")
    if not isinstance(out, dict):
        raise HTTPException(502, "kme answered the cross-check with a non-object body")
    _store("keyrate", out)
    return {**out, "cached": False}


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
    by_phase = {int(p["phase"]): p for p in phases}
    total_pkts = sum(int(p.get("packets", 0)) for p in phases)
    total_bytes = sum(int(p.get("bytes", 0)) for p in phases)
    # Row by row, against Table 1's rows as transcribed separately in
    # paper_budgets.TABLE_1_ROWS. The totals alone could not catch two
    # compensating per-phase edits, and the "paper totals" they were compared
    # with are sums of those same rows -- Table 1 prints no total.
    rows = []
    for r in budgets["table1_rows"]:
        phase = by_phase.get(int(r["phase"]), {})
        rows.append({
            "component": r["component"],
            "phase": r["phase"],
            "paper_packets": r["packets"],
            "paper_bytes": r["bytes"],
            "phase_packets": phase.get("packets"),
            "phase_bytes": phase.get("bytes"),
            "packets_match": phase.get("packets") == r["packets"],
            "bytes_match": phase.get("bytes") == r["bytes"],
        })
    # Phases the table has no row for must carry no traffic, or the totals
    # would hide a budget that the per-row check never looks at.
    tabled = {int(r["phase"]) for r in budgets["table1_rows"]}
    untabled_quiet = all(int(p.get("packets", 0)) == 0 and int(p.get("bytes", 0)) == 0
                         for n, p in by_phase.items() if n not in tabled)
    return {
        "phases": phases,
        "table1_rows": rows,
        "computed_total_packets": total_pkts,
        "computed_total_bytes": total_bytes,
        # Kept under their old names for existing readers; see
        # `paper_totals_source` for what they are.
        "paper_total_packets": budgets["paper_total_packets"],
        "paper_total_bytes": budgets["paper_total_bytes"],
        "paper_totals_source": paper_budgets.PAPER_TOTALS_SOURCE,
        "packets_match": untabled_quiet and all(r["packets_match"] for r in rows)
                         and total_pkts == budgets["paper_total_packets"],
        "bytes_match": untabled_quiet and all(r["bytes_match"] for r in rows)
                       and total_bytes == budgets["paper_total_bytes"],
        "reference": "Spooren et al. arXiv:2604.05599 Evaluation Test 1, Table 1",
    }


# ----------------------- VPN Protocols (Phase 9-A) -----------------------
# Both lanes answer with the SAME key set in every state -- success, error and
# absent -- so a consumer never has to branch on which shape it received. The
# templates below are the single definition of those key sets; every return
# path starts from one of them rather than restating the keys, which is what
# let the WireGuard branch drift to a two-key dict on its default path while a
# comment on the IPsec branch claimed the invariant held for both.
def _wg_unknown(status: str) -> dict[str, Any]:
    """The WireGuard lane's key set, with nothing measured.

    `proposal` is None and stays None. WireGuard negotiates no cipher suite --
    ChaCha20-Poly1305 and Noise_IKpsk2 are fixed by the protocol, and `wg show`
    reports neither -- so any string here would be a constant this file made up.
    It used to hold "ChaCha20-Poly1305 + Noise + PSK". Moving that constant
    server-side would only have changed which file states it as though measured.
    The handshake fields (`active_sa`, `peers_fresh`, `last_handshake_s`)
    replace it with something actually observable. `peers_with_psk` is
    reported beside them but shows only that some key is set, possibly the
    entrypoint's placeholder; see _WG_PSK_RE.

    `fresh_within_s` is not a measurement and is therefore set here too: it is
    the definition `peers_fresh` is counted against (WG_REJECT_AFTER_TIME_S),
    carried in the response so that a reader never has to restate WireGuard's
    constant to label the count.
    """
    return {
        "name": "wireguard",
        "status": status,
        "active_sa": None,
        "peers_fresh": None,
        "fresh_within_s": WG_REJECT_AFTER_TIME_S,
        "proposal": None,
        "last_handshake": None,
        "last_handshake_s": None,
        "peers": None,
        "peers_with_psk": None,
    }


def _ipsec_unknown(status: str) -> dict[str, Any]:
    """The IPsec lane's key set, with nothing measured."""
    return {
        "name": "ipsec",
        "status": status,
        "active_sa": None,
        "proposal": None,
        "last_handshake": None,
        "pq_key_exchange": None,
        "ppk_used": None,
        "ppk_id": None,
        "ppk_required": None,
        "child_sas": None,
    }


# One CHILD_SA block from `swanctl --list-sas`, at four spaces of indent:
#
#     in  cb1df209,      0 bytes,     0 packets
#     out c15c9a27,   1680 bytes,    20 packets,     3s ago
#
# Format from swanctl/commands/list_sas.c:194-224 -- the SPI may carry a
# "/<cpi>" suffix and an optional " (mark .../if-id ...)" group before the
# comma, and an optional ", %5ss ago" after the packet count. Counters are
# printed with `%6s` / `%5s` of a plain integer, so the whitespace is variable
# and there are no thousands separators.
_CHILD_DIR_RE = re.compile(
    r"^\s{4}(in|out)\s+([0-9a-fA-F]+)(?:/\S+)?(?:\s+\([^)]*\))?,"
    r"\s*(\d+)\s+bytes,\s*(\d+)\s+packets",
)
# The CHILD_SA header, at two spaces:
#     tunnel: #6261, reqid 1, INSTALLED, TUNNEL-in-UDP, ESP:AES_GCM_16-256
_CHILD_HEAD_RE = re.compile(
    r"^\s{2}(\S+):\s*#(\d+),\s*reqid\s+(\d+),\s*([A-Z-]+)"
    r"(?:,\s*([^,]+?))?(?:,\s*ESP:(\S+))?\s*$",
)
# An IKE_SA header sits at column 0, which is what ends a CHILD_SA block.
_IKE_HEAD_RE = re.compile(r"^\S")


def _parse_child_sas(sas: str) -> list[dict[str, Any]]:
    """CHILD_SA byte/packet counters and SPIs, as a line-scanning state machine.

    NOT two `findall`s over the whole text. During a rekey window `--list-sas`
    prints two `tunnel:` blocks under one IKE_SA, and pairing the Nth `in` line
    with the Nth `out` line across the whole document silently mixes the old
    SA's inbound counters with the new SA's outbound ones. Scanning line by line
    and closing a block when the indent drops is the only form that stays
    correct while a rekey is in flight -- which is exactly when someone is
    looking.

    An absent direction is None, never 0. charon omits the line it has nothing
    for, and "no outbound line" must not read as "zero bytes sent".
    """
    children: list[dict[str, Any]] = []
    cur: dict[str, Any] | None = None

    def _close() -> None:
        nonlocal cur
        if cur is not None:
            children.append(cur)
            cur = None

    for line in sas.splitlines():
        head = _CHILD_HEAD_RE.match(line)
        if head:
            _close()
            cur = {
                "name": head.group(1),
                "unique_id": int(head.group(2)),
                "reqid": int(head.group(3)),
                "state": head.group(4),
                "mode": head.group(5),
                "esp_proposal": head.group(6),
                "in": None,
                "out": None,
            }
            continue
        if _IKE_HEAD_RE.match(line):
            # Back at column 0: a new IKE_SA, so the previous child is complete.
            _close()
            continue
        if cur is None:
            continue
        d = _CHILD_DIR_RE.match(line)
        if d:
            cur[d.group(1)] = {
                "spi": d.group(2),
                "bytes": int(d.group(3)),
                "packets": int(d.group(4)),
            }
    _close()
    return children


def _sample_ipsec(cli, container: str) -> dict[str, Any]:
    """One node's IPsec view. Two `docker exec`s; never raises."""
    try:
        c = cli.containers.get(container)
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
                "swanctl failed in %s (list-sas rc=%s, list-conns rc=%s): %s",
                container, rc_sas, rc_conns, detail.strip()[:ERROR_TEXT_MAX_CHARS],
            )
            # Same keys as the success path, so a consumer never has to branch
            # on which shape it received. Seeded from the template rather than
            # restated, so the two cannot drift apart -- which is how the
            # WireGuard branch ended up with a two-key default while a comment
            # claimed the invariant held for both.
            #
            # active_sa is None, not 0: swanctl did not answer, so "we looked
            # and there are none" is not something we know.
            return _ipsec_unknown("error")
        return _parse_ipsec_sas(
            sas.decode("utf-8", errors="replace"),
            conns.decode("utf-8", errors="replace"),
        )
    except Exception as e:
        log.warning("ipsec status unavailable for %s: %s", container, e)
        return _ipsec_unknown("absent")


def _sample_wg(container, iface: str, cmd: str) -> dict[str, Any]:
    """One WireGuard interface's view, in `_wg_unknown`'s key set; never raises.

    The same rules for wg0 and wg1, because the failure they guard against is
    the same on both: a `wg show` that failed outright must not render as a
    healthy lane.
    """
    try:
        rc, out = container.exec_run(cmd)
    except Exception as e:
        # Same outcome as the IPsec branch for an exec that could not run.
        log.warning("wireguard status unavailable for %s: %s", iface, e)
        return _wg_unknown("absent")
    text = out.decode("utf-8", errors="replace")
    if rc != 0:
        # Previously a non-zero rc degraded to status "running", which
        # VpnProtocols.tsx renders GREEN -- so a lane whose `wg show` failed
        # outright looked healthy. The IPsec branch has said "error" for this
        # case since it was written; this one matches. On a node without wg1
        # (a deployment from before release 0.2.0) `wg show wg1` exits 1, so
        # the data tunnel reads "error" there, which is what it is.
        log.warning("wg show %s failed (rc=%s): %s", iface, rc, text.strip()[:ERROR_TEXT_MAX_CHARS])
        return _wg_unknown("error")
    return _parse_wg(text)


def _both_ends(alice: dict[str, Any], bob: dict[str, Any]) -> dict[str, Any]:
    """Aggregate the two nodes' views into facts that need BOTH to be known.

    Computed server-side, not in the browser, for a specific reason: `null &&
    true` is falsy in JavaScript, so a client-side `a.ppk_used && b.ppk_used`
    would render "not in use" for "one end did not answer". Here the three
    outcomes stay distinct -- True, False, and None for "could not tell".
    """
    def _both(key: str) -> bool | None:
        a, b = alice.get(key), bob.get(key)
        if a is None or b is None:
            return None
        return bool(a) and bool(b)

    # alice's outbound SPI must be bob's inbound one, and vice versa. This is
    # the only field here that could not be faked by one end alone: an SPI is
    # chosen by the receiver and echoed by the sender, so a match proves the
    # two containers are describing the same pair of ESP SAs rather than two
    # unrelated tunnels that both happen to be up.
    def _spis(node: dict[str, Any]) -> tuple[set[str], set[str]] | None:
        kids = node.get("child_sas")
        if not kids:
            return None
        return (
            {k["in"]["spi"] for k in kids if k.get("in")},
            {k["out"]["spi"] for k in kids if k.get("out")},
        )

    a_spis, b_spis = _spis(alice), _spis(bob)
    if a_spis is None or b_spis is None or not (a_spis[0] or a_spis[1]):
        spi_paired: bool | None = None
    else:
        spi_paired = bool(a_spis[1] & b_spis[0]) and bool(a_spis[0] & b_spis[1])

    return {
        # Deliberately NEW names, not a redefinition of the flat `ppk_required`.
        # A shape change fails loudly; a meaning change fails silently -- a
        # cached frontend would render alice-only data under a both-ends label
        # and nothing would break.
        "ppk_required_both_ends": _both("ppk_required"),
        "ppk_used_both_ends": _both("ppk_used"),
        "pq_key_exchange_both_ends": _both("pq_key_exchange"),
        "spi_paired": spi_paired,
    }


# Sampling `/api/vpn/protocols` costs six `docker exec`s (wg show for wg0 and
# wg1, and list-sas + list-conns on each of the two IPsec nodes). The page
# polls every 5 s per viewer (VPN_POLL_MS in VpnProtocols.tsx), matched by the
# 5 s default below. At a 3 s poll against a 2 s TTL every poll from every
# viewer missed the cache.
# A short TTL collapses concurrent viewers onto one sample without introducing
# a background task -- main.py deliberately has none.
#
# Failure shapes are cached too. Caching only successes would make a broken
# lane the expensive case, which is precisely when the host is least able to
# absorb it.
VPN_SAMPLE_TTL_S = float(os.environ.get("VPN_SAMPLE_TTL_S", "5.0"))
_vpn_sample: dict[str, Any] = {}


@app.get("/api/vpn/protocols")
def vpn_protocols():
    """Live status of both VPN lanes, from both ends of the IPsec one.

    A plain `def`, not `async def`. Every call inside is a blocking
    `exec_run`; under `async def` those six round trips run ON the event loop
    and stall every other request for their duration. FastAPI dispatches a sync
    handler to its threadpool instead.
    """
    now = time.monotonic()
    cached = _vpn_sample.get("v")
    if cached is not None and (now - cached["at"]) < VPN_SAMPLE_TTL_S:
        return cached["value"]

    cli = app.state.docker
    wg_status: dict[str, Any] = _wg_unknown("absent")
    wg_data_status: dict[str, Any] = _wg_unknown("absent")
    alice_ipsec: dict[str, Any] = _ipsec_unknown("absent")
    bob_ipsec: dict[str, Any] = _ipsec_unknown("absent")

    if cli is not None:
        try:
            c = cli.containers.get("alice")
        except Exception as e:
            # The IPsec branch logs; this one used to swallow silently, so a
            # WireGuard lane that was never reachable looked identical to one
            # that was simply absent.
            log.warning("wireguard status unavailable: %s", e)
        else:
            wg_status = _sample_wg(c, "wg0", WG_SHOW_CMD)
            wg_data_status = _sample_wg(c, "wg1", WG_DATA_SHOW_CMD)

        alice_ipsec = _sample_ipsec(cli, "alice-ipsec")
        bob_ipsec = _sample_ipsec(cli, "bob-ipsec")

    value = {
        # The flat WireGuard fields keep meaning what they meant before: alice's
        # wg0, the hop tunnel. wg1, the data tunnel that runs inside it, is
        # additive under `data_tunnel` with the same key set, so a consumer
        # reads both with one renderer.
        "wireguard": {
            **wg_status,
            "interface": "wg0",
            "psk_source": WG_PSK_SOURCE["wg0"],
            "data_tunnel": {
                **wg_data_status,
                "interface": "wg1",
                "psk_source": WG_PSK_SOURCE["wg1"],
            },
        },
        # The flat IPsec fields keep meaning exactly what they meant before:
        # alice's view. Adding `nodes` and the *_both_ends aggregates alongside
        # them is additive; redefining these would have been a silent change.
        "ipsec": {
            **alice_ipsec,
            "nodes": {"alice": alice_ipsec, "bob": bob_ipsec},
            **_both_ends(alice_ipsec, bob_ipsec),
        },
        # So a reader can tell a fresh sample from a cached one rather than
        # inferring it from how fast the numbers move.
        "observed_at": time.time(),
        "cache_ttl_s": VPN_SAMPLE_TTL_S,
    }
    _vpn_sample["v"] = {"at": now, "value": value}
    return value


# Rotations get their own endpoint, at their own cadence.
#
# VERIFICATION_CHECKLIST row 2.14 is a ten-minute procedure, not a snapshot.
# Folding it into /api/vpn/protocols would mean reading two containers' whole
# log streams every 3 s per viewer -- server compute the public demo is
# supposed to avoid, and orders of magnitude more expensive than the six
# `exec_run`s above.
#
# The pattern anchors on the adapter's message text, never on a line prefix,
# because the prefix changed with the arnika pin. At 3a8cc13 the adapter's
# `log.Printf` line was the whole line:
#   2026/09/25 06:48:38 [INFO] [VICI] PPK rotated (id=qkd-alice-3 ppk_id=... bytes=32)
# At f4cf9ba arnika installs an slog TextHandler as the default logger
# (logging.go:42 and :63 there), which routes the standard `log` package
# through it, so the same text arrives as the quoted `msg` of a key=value line:
#   time=... level=INFO msg="[INFO] [VICI] PPK rotated (id=qkd-alice-3 ppk_id=... bytes=32)" arnika_id=11
# The text inside the quotes is unchanged (no quote or backslash in it to
# escape), so this pattern counts both forms. tests/test_wg_data_tunnel_is_reported.py
# pins it against each. A LOG_LEVEL above info drops the bridged lines, and
# the counts with them; the entrypoint sets info.
_ROTATION_RE = re.compile(r"PPK rotated \(id=(\S+?) ")
# Rotation ATTEMPTS are not outcomes. arnika-vici logs "PPK rotated" when it
# queues the reauthentication, before IKE_AUTH has run, so on the live demo the
# 16 failed reauthentications of 2026-09-16..25 were invisible here: 25,249
# rotations, 25,249 counted. These two count what happened next.
#   N(AUTH_FAILED)       charon's message log for an IKE_AUTH carrying the
#                        AUTHENTICATION_FAILED notify, on either role.
#   using PPK for PPK_ID ike_auth.c, logged after derive_ike_keys_ppk()
#                        succeeded -- the PPK was mixed into the IKE keys.
_AUTH_FAILED_RE = re.compile(r"N\(AUTH_FAILED\)")
_PPK_APPLIED_RE = re.compile(r"using PPK for PPK_ID")
ROTATION_WINDOW_MAX_S = int(os.environ.get("VPN_ROTATION_WINDOW_MAX_S", "3600"))
ROTATION_TTL_S = float(os.environ.get("VPN_ROTATION_TTL_S", "15.0"))
_rotation_sample: dict[int, Any] = {}


def _count_rotations(cli, container: str, window_s: int) -> dict[str, Any]:
    """Count 'PPK rotated' lines in a container's recent log.

    Counts only. The log lines themselves are never returned: they carry
    credential ids and peer identities, and this endpoint is public.

    `count: None` plus an `error` string when we could not look. Zero rotations
    and "could not look" must never be the same value -- a stalled arnika and
    an unreachable container are different faults and the first is the one row
    2.14 exists to catch.
    """
    try:
        c = cli.containers.get(container)
        raw = c.logs(since=int(time.time()) - window_s, stdout=True, stderr=True)
        text = raw.decode("utf-8", errors="replace")
    except Exception as e:
        log.warning("could not read %s logs: %s", container, e)
        return {"count": None, "distinct_ids": None, "auth_failed": None,
                "ppk_applied": None, "error": str(e)[:ERROR_TEXT_MAX_CHARS]}
    ids = _ROTATION_RE.findall(text)
    return {
        "count": len(ids),
        # A rotation that reinstalls the SAME credential id is not a rotation.
        # Reporting both makes that visible instead of inflating the count.
        "distinct_ids": len(set(ids)),
        "auth_failed": len(_AUTH_FAILED_RE.findall(text)),
        "ppk_applied": len(_PPK_APPLIED_RE.findall(text)),
        "error": None,
    }


@app.get("/api/vpn/ppk-rotations")
def vpn_ppk_rotations(window_s: int = 600):
    """How many PPK rotations each IPsec node logged in the last `window_s`.

    Bounded and cached: an unbounded window would read the entire log stream of
    two containers on every request.
    """
    # The window used is reported beside the one asked for. It was clamped
    # silently: ?window_s=86400 answered with 3600 and nothing else, so a
    # reader asking for a day of rotations got an hour's and could not tell.
    requested = int(window_s)
    window_s = max(30, min(requested, ROTATION_WINDOW_MAX_S))
    now = time.monotonic()
    cached = _rotation_sample.get(window_s)
    if cached is not None and (now - cached["at"]) < ROTATION_TTL_S:
        return {**cached["value"], "requested_window_s": requested,
                "capped": requested != window_s}

    cli = app.state.docker
    if cli is None:
        nodes = {n: {"count": None, "distinct_ids": None, "auth_failed": None,
                     "ppk_applied": None, "error": "docker not available"}
                 for n in ("alice-ipsec", "bob-ipsec")}
    else:
        nodes = {n: _count_rotations(cli, n, window_s)
                 for n in ("alice-ipsec", "bob-ipsec")}

    value = {
        "window_s": window_s,
        "nodes": nodes,
        "counts": {
            "count": "'PPK rotated' lines: reauthentications QUEUED, not outcomes",
            "auth_failed": "IKE_AUTH carrying AUTHENTICATION_FAILED (either role)",
            "ppk_applied": "'using PPK for PPK_ID': the PPK was mixed into the IKE keys",
        },
        "observed_at": time.time(),
        "cache_ttl_s": ROTATION_TTL_S,
        # What this endpoint does NOT establish, said here rather than left for
        # a reader to assume. Row 2.14 also asserts "concurrency 1 across 20
        # samples"; proving that needs a sampler running between requests, and
        # main.py deliberately runs no background tasks (see `lifespan`). A
        # single instantaneous `active_sa` from /api/vpn/protocols is the most
        # this API can honestly offer.
        "note": (
            "Counts log lines in a window. It does not establish that SA "
            "concurrency stayed at 1 throughout -- that needs repeated sampling, "
            "which this server does not do. Read active_sa from "
            "/api/vpn/protocols for an instantaneous value."
        ),
    }
    _rotation_sample[window_s] = {"at": now, "value": value}
    return {**value, "requested_window_s": requested, "capped": requested != window_s}


# `wg show wg0` renders one block per peer, e.g.
#   interface: wg0
#     public key: <base64>
#     private key: (hidden)
#     listening port: 51820
#
#   peer: <base64>
#     preshared key: (hidden)
#     endpoint: 10.30.0.11:51821
#     allowed ips: 10.0.0.2/32
#     latest handshake: 1 minute, 32 seconds ago
#     transfer: 726.21 KiB received, 980.89 KiB sent
#
# Two of those lines are CONDITIONAL, which is what makes them worth reading.
# From wireguard-tools src/show.c:
#   * `preshared key:` prints only when `peer->flags & WGPEER_HAS_PRESHARED_KEY`,
#     so its presence shows that SOME preshared key is installed on that peer,
#     and nothing more. Since release 0.2.0 the node entrypoint installs a
#     random `wg genpsk` placeholder on every wg0 and wg1 peer when it creates
#     it (nodes/alice/entrypoint.sh, add_wg_peer), so that no handshake can
#     complete before the keying daemon has written the same key on both ends.
#     A full `peers_with_psk` count is therefore expected before arnika or
#     Rosenpass has written anything, and is not evidence that either did.
#     Which process is meant to write it is configuration (WG_PSK_SOURCE).
#   * `latest handshake:` prints only when the handshake time is non-zero, and
#     a completed handshake IS the evidence: the preshared key is mixed into
#     every Noise_IKpsk2 handshake, so one completes only when both ends hold
#     the same key -- on wg0 arnika's, on wg1 Rosenpass's -- and its age says
#     how recently that held. `active_sa`, `peers_fresh` and
#     `last_handshake_s` carry it; they are what replaced the invented
#     `proposal` constant. A ping that answers over the interface shows only
#     that the current WireGuard session carries traffic, not that the
#     preshared key written most recently is in use (see WG_REJECT_AFTER_TIME_S
#     below for why).
#
# The line is also PERMANENT. The handshake time is per peer and is cleared
# only when the peer is created, and the entrypoint adds each peer when it
# creates the interface, so once a peer has handshaked the line stays until the
# interface is recreated. A peer whose two ends later diverge onto different
# preshared keys, after a rotation for example, keeps its line and only its age
# grows. So `active_sa` ("ever handshaked since the interface came up") cannot
# fall, and `peers_fresh` is the count that can.
#
# WireGuard's REJECT_AFTER_TIME, in seconds: Linux drivers/net/wireguard/
# messages.h, `enum limits`, `REJECT_AFTER_TIME = 180`; wireguard-go, the
# userspace fallback, has the same value (device/constants.go,
# `RejectAfterTime = time.Second * 180`). In the kernel, decrypt_packet()
# (receive.c) rejects a keypair whose `receiving.birthdate` has reached that
# age and wg_packet_send_staged_packets() (send.c) does the same for
# `sending.birthdate`. derive_keys() (noise.c) sets the birthdate when the
# session keys are derived, which is never after the moment `latest
# handshake:` records: the initiator derives them on the response and then
# calls wg_timers_handshake_complete(), which stamps the handshake time; the
# responder derives them when it sends the response, and its handshake is
# stamped later, on the first data packet. So a peer whose latest handshake is
# at least this old holds no session key WireGuard will still use. Every peer
# here has a persistent keepalive (WG_PERSISTENT_KEEPALIVE_S in the node
# entrypoint), so a working peer always has traffic, and on traffic WireGuard
# starts a new handshake at REKEY_AFTER_TIME (120 s, same enum), before that
# age.
#
# What a fresh handshake does NOT show: that the preshared key written most
# recently is in use. A new preshared key applies only at the next handshake,
# and the session keypair from the last completed one stays usable until it is
# this old. So after the ends diverge the count stays full for up to this long
# before it falls, and a ping over the interface keeps answering until that
# keypair reaches this age. Neither shows the latest write in use. A handshake
# completed after that write on both ends does: a `last_handshake_s` smaller
# than the time since arnika's (wg0) or Rosenpass's (wg1) last write, which
# this API does not report.
WG_REJECT_AFTER_TIME_S = 180

_WG_PEER_RE = re.compile(r"^peer:\s*\S+", re.M)
_WG_PSK_RE = re.compile(r"^\s+preshared key:", re.M)
_WG_HANDSHAKE_RE = re.compile(r"^\s+latest handshake:\s*(.+?)\s*$", re.M)

# The handshake value comes from show.c's ago(), which has exactly three shapes:
#   "Now"
#   "(System clock wound backward; connection problems may ensue.)"
#   "<pretty_time> ago"
# and pretty_time() OMITS zero components:
#
#   if (years)  ... if (days) ... if (hours) ... if (minutes) ... if (seconds)
#
# so "2 days, 5 seconds ago" is a legal rendering and a positional parse would
# read the 5 as minutes. Match unit names, never positions. Units are singular
# at 1 and plural otherwise, hence the optional s.
_WG_AGO_COMPONENT_RE = re.compile(r"(\d+)\s+(year|day|hour|minute|second)s?\b")
# Same arithmetic show.c uses: a year is 365 * 24 * 60 * 60, not a calendar year.
_WG_UNIT_SECONDS = {
    "second": 1, "minute": 60, "hour": 3600, "day": 86400, "year": 365 * 86400,
}


def _wg_handshake_seconds(raw: str) -> int | None:
    """Age in seconds from one `latest handshake:` value, or None if unreadable.

    None means "we could not read it", never "0 seconds". show.c renders a
    zero-second age as the literal "Now", so 0 is a real measurement and has to
    stay distinguishable from a parse failure -- including for the
    clock-wound-backward case, where the age is genuinely unknown rather than
    small.
    """
    value = raw.strip()
    if value == "Now":
        return 0
    if "wound backward" in value:
        return None
    components = _WG_AGO_COMPONENT_RE.findall(value)
    if not components:
        return None
    return sum(int(n) * _WG_UNIT_SECONDS[unit] for n, unit in components)


def _parse_wg(text: str) -> dict[str, Any]:
    """Derive WireGuard lane status from real `wg show` output.

    Every field is measured or None. The version this replaced reported
    `proposal` as the literal "ChaCha20-Poly1305 + Noise + PSK" and
    `last_handshake` as the literal "via wg show" -- a description of where a
    value would come from, shipped as the value -- and both went out over the
    public API. See `_wg_unknown` for why `proposal` is None permanently.

    `active_sa` counts peers that have completed a handshake at any time since
    the interface came up, matching what the field means on the IPsec side
    (established SAs) rather than the previous `1 if "latest handshake" in
    text else 0`, which could not exceed 1 and ignored the exit code entirely.
    That meaning is unchanged, and so is `status`, which reads "established"
    on the same condition. Neither can fall while the interface stays up,
    because the `latest handshake:` line is permanent (see above). /vpn
    renders its WireGuard badge from `peers_fresh` instead (wgStatusBadge.ts
    in the frontend); this field keeps the lifetime meaning.

    `peers_fresh` is the count that can fall: peers whose latest handshake is
    younger than WG_REJECT_AFTER_TIME_S, so that they still hold a session key
    WireGuard will use. It is None when any handshake age is unreadable (the
    clock-wound-backward rendering), because such a peer is neither known to
    be fresh nor known to be stale.
    """
    peers = len(_WG_PEER_RE.findall(text))
    if peers == 0:
        # `wg show` succeeded but the interface has no peers -- the tunnel
        # cannot be established, and saying "running" would overstate it.
        return {**_wg_unknown("running"), "peers": 0, "peers_with_psk": 0,
                "active_sa": 0, "peers_fresh": 0}

    handshakes = [_wg_handshake_seconds(m) for m in _WG_HANDSHAKE_RE.findall(text)]
    readable = [s for s in handshakes if s is not None]
    # Freshest peer, which is what a single "last handshake" figure can honestly
    # mean when there is more than one peer.
    age = min(readable) if readable else None
    fresh = (sum(1 for s in readable if s < WG_REJECT_AFTER_TIME_S)
             if len(readable) == len(handshakes) else None)

    return {
        **_wg_unknown("established" if handshakes else "running"),
        "active_sa": len(handshakes),
        "peers_fresh": fresh,
        "proposal": None,
        "last_handshake": f"{age}s ago" if age is not None else None,
        "last_handshake_s": age,
        "peers": peers,
        "peers_with_psk": len(_WG_PSK_RE.findall(text)),
    }


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

    # Seeded from the shared template so the success and error paths cannot
    # drift to different key sets; see _ipsec_unknown.
    return {
        **_ipsec_unknown(status),
        "active_sa": established,
        # None rather than a plausible-looking constant, so the UI can tell
        # "not negotiated yet" apart from "negotiated X".
        "proposal": proposal,
        "last_handshake": f"{age.group(1)}{age.group(2)} ago" if age else None,
        # RFC 9370: an additional ML-KEM key exchange was negotiated.
        #
        # Tri-state, deliberately. This was `"ML_KEM" in (proposal or "") or None`,
        # which yields True or None and NEVER False -- so "we read the proposal
        # and there is no ML-KEM in it" was indistinguishable from "we never
        # got a proposal". Both rendered as an em dash, so nothing on screen
        # could contradict it either.
        "pq_key_exchange": ("ML_KEM" in proposal) if proposal else None,
        # RFC 8784: whether the PPK was actually USED for this IKE_SA.
        #
        # This comment used to read: "charon does not report per-SA PPK use over
        # VICI, so this is honestly labelled as configuration, not as proof of
        # use." That is wrong, and the evidence was already in the output this
        # function is given. strongSwan 6.1.0, three files:
        #
        #   sa/ike_sa.h:261      /** A Postquantum Preshared Key was used when
        #                            this IKE_SA was created */
        #                        COND_PPK = (1<<13),
        #   vici/vici_query.c:640   add_condition(b, ike_sa, "ppk", COND_PPK);
        #   swanctl/list_sas.c:325  if (streq(ike->get(ike, "ppk"), "yes"))
        #                               printf("/PPK");
        #
        # and the condition is set in ikev2/tasks/ike_auth.c:1187, inside
        # apply_ppk(), only AFTER derive_ike_keys_ppk() has succeeded -- i.e.
        # only once the PPK has actually been mixed into SK_d/SK_pi/SK_pr.
        #
        # So the trailing "/PPK" on the proposal line is per-SA proof of use.
        # We were fetching --list-sas already and discarding the answer, while
        # reading --list-conns for a weaker one.
        "ppk_used": ("/PPK" in proposal) if proposal else None,
        # ...and this stays what it always was: CONFIGURATION, from
        # --list-conns. Kept separate rather than merged, because "the operator
        # required a PPK" and "charon mixed one in" fail independently -- a
        # required PPK that never arrives is exactly the case worth seeing.
        "ppk_id": ppk.group(1) if ppk else None,
        "ppk_required": (ppk.group(2) == "required") if ppk else None,
        # ESP counters and SPIs, per CHILD_SA. `swanctl --list-sas` has always
        # carried these; nothing parsed them, so VERIFICATION_CHECKLIST row
        # 2.11 (and the SPI-pairing half of the both-ends check) could only be
        # executed over SSH. Row 2.3 is served by `ppk_required`, not by these.
        "child_sas": _parse_child_sas(sas),
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

    alice and bob each carry two WireGuard interfaces, so there are two
    alice-bob edges: wg0, the hop tunnel arnika keys, and wg1, the data tunnel
    Rosenpass keys, which runs inside wg0. The labels name "Rosenpass" in full;
    they used to say "RP", which nothing on the page expanded.
    """
    nodes = [
        {"id": "alice", "type": "node", "label": "Alice (wg0 + wg1, arnika, Rosenpass)"},
        {"id": "bob",   "type": "node", "label": "Bob (wg0 + wg1, arnika, Rosenpass)"},
        {"id": "kme-a", "type": "kme",  "label": "BB84 KME (Alice)"},
        {"id": "kme-b", "type": "kme",  "label": "BB84 KME (Bob)"},
    ]
    edges = [
        {"source": "alice", "target": "bob",
         "label": "wg0 hop tunnel (PSK = HKDF(QKD‖PQC-HPKE))"},
        {"source": "alice", "target": "bob",
         "label": "wg1 data tunnel inside wg0 (PSK = Rosenpass)"},
        {"source": "alice", "target": "kme-a", "label": "ETSI 014"},
        {"source": "bob",   "target": "kme-b", "label": "ETSI 014"},
        {"source": "kme-a", "target": "kme-b", "label": "BB84 quantum + classical channel"},
    ]
    return {"nodes": nodes, "edges": edges}


