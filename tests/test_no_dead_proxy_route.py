"""A proxy for a route that does not exist is config shaped like a feature.

`services/webui-frontend/nginx.conf` carried a `location /ws/` forwarding
WebSocket upgrades to `webui-backend`, and `vite.config.ts` carried the matching
dev-server entry. Neither could ever work:

  * `grep -c '@app.websocket' services/webui-backend/app/main.py` -> 0
  * `grep -rn 'new WebSocket' services/webui-frontend/src/` -> nothing
  * live, before removal: `GET /ws/frames` -> 404

`/e2e` and `/paper-flow` moved to client-side simulation and the orchestrators
that once served frames were deleted; the proxies outlived them.

It was not merely dead. The nginx block set `proxy_read_timeout 86400`, so a
client that did upgrade would hold a worker connection open for 24 hours to be
told nothing.

This is the same shape as the `/api/sim/optimize` route deleted earlier today:
plausible-looking configuration for a capability that is not there.
"""
from __future__ import annotations

import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parents[1]
NGINX = REPO / "services" / "webui-frontend" / "nginx.conf"
VITE = REPO / "services" / "webui-frontend" / "vite.config.ts"
BACKEND = REPO / "services" / "webui-backend" / "app" / "main.py"
SRC = REPO / "services" / "webui-frontend" / "src"


def test_the_backend_still_declares_no_websocket_route():
    """The premise. If this changes, the proxies should come back."""
    n = len(re.findall(r"@app\.websocket", BACKEND.read_text(encoding="utf-8")))
    assert n == 0, (
        f"webui-backend now declares {n} websocket route(s); the nginx and vite "
        f"proxies were removed on the basis that it had none")


def test_no_frontend_code_opens_a_socket():
    hits = [str(f.relative_to(REPO)) for f in SRC.rglob("*.ts*")
            if re.search(r"new WebSocket\b", f.read_text(encoding="utf-8"))]
    assert hits == [], f"these open a WebSocket with no server route: {hits}"


def test_nginx_has_no_websocket_location():
    body = NGINX.read_text(encoding="utf-8")
    live = "\n".join(l for l in body.splitlines() if not l.strip().startswith("#"))
    assert "location /ws" not in live, (
        "the /ws/ proxy is back. It forwards to a backend with no websocket "
        "routes, and its 86400 s read timeout holds a worker open all day")


def test_the_dev_proxy_matches_production():
    """A dev server that proxies what nginx does not is its own trap."""
    body = VITE.read_text(encoding="utf-8")
    live = re.sub(r"//.*", "", body)
    assert '"/ws"' not in live, (
        "vite proxies /ws while nginx does not, so development and production "
        "disagree about a route that works in neither")


def test_both_removals_explain_themselves():
    """A silent deletion invites a silent restoration."""
    for path in (NGINX, VITE):
        txt = path.read_text(encoding="utf-8")
        assert "websocket" in txt.lower() or "WebSocket" in txt, (
            f"{path.name} no longer records why the /ws proxy went")
