#!/usr/bin/env python3
"""Load every route of the built SPA under the site's Content-Security-Policy.

Serves `services/webui-frontend/dist` on 127.0.0.1 with the policy that
deploy/Caddyfile sends, opens each route that src/App.tsx declares in headless
Chrome, and fails if Chrome reports any CSP violation or if a route renders
nothing into #root (a blocked script leaves the shell empty). There is no
backend: /api and /ws answer 404, so a page shows its "Not observed" state, which
is still what runs on load.

    npx vite build              # in services/webui-frontend
    python3 scripts/csp_smoke.py

Exit status: 0 every route clean, 1 a violation or an empty route, 2 the check
could not run (no build, no Chrome, no enforced policy). CI also runs it once
with a policy that lacks the inline-style hash and expects 1, so the gate is
shown to fail on the defect it exists for, not only to pass.

Standard library only: CI's frontend job has no Python environment of its own.
"""
from __future__ import annotations

import argparse
import functools
import http.server
import mimetypes
import re
import shutil
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROUTE_RE = re.compile(r'<Route\s+path="([^"*]+)"')
CSP_LINE = re.compile(r'^\s*Content-Security-Policy\s+"([^"]+)"\s*$')
TYPES = {".js": "text/javascript", ".css": "text/css", ".wasm": "application/wasm",
         ".svg": "image/svg+xml", ".json": "application/json", ".html": "text/html"}


def enforced_policy(caddyfile: Path) -> str | None:
    """The value of the enforced (not report-only) CSP line in the Caddyfile."""
    found = [m.group(1) for m in map(CSP_LINE.match, caddyfile.read_text().splitlines()) if m]
    return found[0] if len(found) == 1 else None


def routes(app_tsx: Path) -> list[str]:
    return ROUTE_RE.findall(app_tsx.read_text())


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, policy: str, dist: Path, **kw):
        self.policy, self.dist = policy, dist
        super().__init__(*args, directory=str(dist), **kw)

    def log_message(self, *args):  # quiet
        pass

    def end_headers(self):
        self.send_header("Content-Security-Policy", self.policy)
        self.send_header("X-Content-Type-Options", "nosniff")
        super().end_headers()

    def guess_type(self, path):
        return TYPES.get(Path(str(path)).suffix, mimetypes.guess_type(str(path))[0] or "application/octet-stream")

    def send_head(self):
        path = self.path.split("?", 1)[0].split("#", 1)[0]
        if path.startswith("/api/") or path == "/ws" or path.startswith("/ws/"):
            self.send_error(404, "no backend in this check")
            return None
        target = (self.dist / path.lstrip("/")).resolve()
        if self.dist not in target.parents and target != self.dist:
            self.send_error(404)
            return None
        if not target.is_file():
            self.path = "/index.html"  # SPA fallback, as nginx does
        return super().send_head()


def find_chrome(explicit: str | None) -> str | None:
    if explicit:
        return explicit if shutil.which(explicit) or Path(explicit).is_file() else None
    for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "chrome"):
        if shutil.which(name):
            return shutil.which(name)
    return None


def visit(chrome: str, url: str, profile: Path, budget_ms: int, no_sandbox: bool) -> tuple[str, str]:
    cmd = [chrome, "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
           f"--user-data-dir={profile}", "--enable-logging=stderr", "--v=0",
           f"--virtual-time-budget={budget_ms}", "--dump-dom", url]
    if no_sandbox:
        cmd.insert(1, "--no-sandbox")
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    return p.stdout, p.stderr


def violations(stderr: str) -> list[str]:
    out = []
    for line in stderr.splitlines():
        if "Content Security Policy" not in line:
            continue
        m = re.search(r"(Refused to [^.]*|Applying inline style violates|Executing inline [a-z ]*violates"
                      r"|Evaluating a string as JavaScript violates)[^']*'([a-z-]+)", line)
        out.append(f"{m.group(2)}: {m.group(1)}" if m else line.strip()[-160:])
    return out


def rendered(dom: str) -> bool:
    m = re.search(r'<div id="root">(.*)', dom, re.S)
    return bool(m) and not m.group(1).lstrip().startswith("</div>")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dist", type=Path, default=ROOT / "services/webui-frontend/dist")
    ap.add_argument("--caddyfile", type=Path, default=ROOT / "deploy/Caddyfile")
    ap.add_argument("--app", type=Path, default=ROOT / "services/webui-frontend/src/App.tsx")
    ap.add_argument("--policy", help="use this policy instead of the Caddyfile's (to show the gate fails)")
    ap.add_argument("--chrome", help="path to Chrome or Chromium (default: first one on PATH)")
    ap.add_argument("--no-sandbox", action="store_true", help="pass --no-sandbox to Chrome (CI runners)")
    ap.add_argument("--budget-ms", type=int, default=12000, help="virtual time per route")
    a = ap.parse_args()

    dist = a.dist.resolve()
    if not (dist / "index.html").is_file():
        print(f"error: no build at {dist} (run `npx vite build` in services/webui-frontend)", file=sys.stderr)
        return 2
    policy = a.policy or enforced_policy(a.caddyfile)
    if not policy:
        print(f"error: {a.caddyfile} has no single enforced Content-Security-Policy line", file=sys.stderr)
        return 2
    paths = routes(a.app)
    if not paths:
        print(f"error: no <Route path> in {a.app}", file=sys.stderr)
        return 2
    chrome = find_chrome(a.chrome)
    if not chrome:
        print("error: no Chrome or Chromium found", file=sys.stderr)
        return 2
    version = subprocess.run([chrome, "--version"], capture_output=True, text=True).stdout.strip()

    server = http.server.ThreadingHTTPServer(
        ("127.0.0.1", 0), functools.partial(Handler, policy=policy, dist=dist))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    print(f"{version}; {len(paths)} routes; policy {'from --policy' if a.policy else 'from ' + str(a.caddyfile.name)}")

    bad = 0
    with tempfile.TemporaryDirectory(prefix="csp-smoke-") as tmp:
        for i, route in enumerate(paths):
            dom, err = visit(chrome, base + route, Path(tmp) / f"p{i}", a.budget_ms, a.no_sandbox)
            found, ok = violations(err), rendered(dom)
            status = "ok" if ok and not found else "FAIL"
            bad += status == "FAIL"
            print(f"  {route:<16} {status:<4} violations={len(found)} rendered={'yes' if ok else 'NO'}")
            for v in sorted(set(found)):
                print(f"      {v}")
    server.shutdown()
    print(f"{len(paths) - bad}/{len(paths)} routes clean")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
