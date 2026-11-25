"""scripts/check-public-headers.sh passes the headers deploy/Caddyfile sets, and only those.

It is check 11 of scripts/verify-demo-hardening.sh: the one that notices a deploy
which left the old caddy container running, so the site answers 200 everywhere
with yesterday's headers. Like tests/test_release_gates_can_actually_fail.py,
each case runs the real script and asserts the direction: the headers the
Caddyfile sets exit 0, and each way of getting them wrong exits 1 -- a
report-only policy, a policy that differs, HSTS widened to subdomains, nosniff
missing, a Server header back, Caddy's Via back. A Caddyfile with no enforced policy exits 2,
because then there is nothing to compare with, which is not a pass.

The site is a local HTTP server that sends exactly the headers a case names
(Python's own Server header suppressed); the script reads only the root's
response headers, so nothing else needs to exist.
"""
from __future__ import annotations

import http.server
import re
import shutil
import subprocess
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check-public-headers.sh"
POLICY = re.search(r'^\s*Content-Security-Policy "([^"]+)"\s*$',
                   (ROOT / "deploy/Caddyfile").read_text(), re.M).group(1)
GOOD = {
    "Strict-Transport-Security": "max-age=31536000",
    "X-Content-Type-Options": "nosniff",
    "Content-Security-Policy": POLICY,
}

pytestmark = pytest.mark.skipif(shutil.which("curl") is None, reason="the script uses curl")


def _serve(headers: dict[str, str]):
    class Handler(http.server.BaseHTTPRequestHandler):
        def send_response(self, code, message=None):  # no automatic Server header
            self.send_response_only(code, message)
            self.send_header("Date", self.date_time_string())

        def do_GET(self):
            self.send_response(200)
            for k, v in headers.items():
                self.send_header(k, v)
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"ok")

        def log_message(self, *args):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def _run(headers: dict[str, str], env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    server = _serve(headers)
    try:
        return subprocess.run(["sh", str(SCRIPT), f"http://127.0.0.1:{server.server_address[1]}"],
                              capture_output=True, text=True, timeout=60, env=env)
    finally:
        server.shutdown()


def test_the_caddyfile_headers_pass():
    r = _run(GOOD)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "ok: " in r.stdout


@pytest.mark.parametrize("name,headers", [
    ("report-only instead of enforced",
     {**{k: v for k, v in GOOD.items() if k != "Content-Security-Policy"},
      "Content-Security-Policy-Report-Only": POLICY}),
    ("report-only beside the enforced one",
     {**GOOD, "Content-Security-Policy-Report-Only": POLICY}),
    ("a policy that differs",
     {**GOOD, "Content-Security-Policy": POLICY.replace("style-src 'self'", "style-src 'self' 'unsafe-inline'")}),
    ("no policy", {k: v for k, v in GOOD.items() if k != "Content-Security-Policy"}),
    ("HSTS widened to subdomains", {**GOOD, "Strict-Transport-Security": "max-age=31536000; includeSubDomains"}),
    ("nosniff missing", {k: v for k, v in GOOD.items() if k != "X-Content-Type-Options"}),
    ("a Server header", {**GOOD, "Server": "nginx/1.31.9"}),
    ("a Via header", {**GOOD, "Via": "1.1 Caddy"}),
])
def test_each_wrong_header_fails(name, headers):
    r = _run(headers)
    assert r.returncode == 1, f"{name}: exit {r.returncode}\n{r.stdout}{r.stderr}"
    assert "::error::" in r.stdout


def test_no_enforced_policy_in_the_caddyfile_cannot_pass(tmp_path):
    caddyfile = tmp_path / "Caddyfile"
    caddyfile.write_text(f'\theader {{\n\t\tContent-Security-Policy-Report-Only "{POLICY}"\n\t}}\n')
    r = _run(GOOD, env={"CADDYFILE": str(caddyfile), "PATH": "/usr/bin:/bin"})
    assert r.returncode == 2, r.stdout + r.stderr


def test_the_hardening_script_runs_it_and_fails_with_it():
    body = (ROOT / "scripts" / "verify-demo-hardening.sh").read_text(encoding="utf-8")
    call = body.index('check-public-headers.sh" "$BASE"')
    branch = body[call:body.index("fi\n", call)]
    assert "else" in branch and "fail=1" in branch.split("else", 1)[1], (
        "check 11 no longer turns a header mismatch into a failing exit status")
