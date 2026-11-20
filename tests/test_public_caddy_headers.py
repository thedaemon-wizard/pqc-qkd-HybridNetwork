"""The public Caddy site sends HSTS, nosniff and a report-only CSP, and drops nginx's Server header.

All four are in one `header` block of the public site in deploy/Caddyfile.
Because the block deletes a field, Caddy defers every operation in it until the
response is written ("header operations are performed immediately unless any of
the headers are being deleted", Caddy's header directive docs), so the added
fields also reach the responses proxied from webui-frontend. A second, separate
`header` line that only sets fields would run immediately instead, which is why
the block is checked as a whole.

HSTS is for this hostname only and for one year: no includeSubDomains, no
preload (RFC 6797; sending max-age=0 undoes it).

The Content-Security-Policy is report-only: it blocks nothing, and the browser
console names what an enforced copy would refuse. The checks below keep the
candidate honest while it is being tried: every source is 'self' or a scheme the
exporters need, the two exceptions stay tied to the code that needs them (the
WebAssembly kernel, the one <style> block of index.html), and it carries neither
'unsafe-inline' nor 'unsafe-eval'. Enforcing it is a separate change that renames
the header, and the first test fails until that change says so.
"""
from __future__ import annotations

import base64
import hashlib
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SITE_OPENER = "{$PUBLIC_HOST} {"
CSP_RO = "Content-Security-Policy-Report-Only"


def _public_site_lines() -> list[str]:
    """Directive lines of the public site block, comments and blank lines removed."""
    lines = (REPO / "deploy/Caddyfile").read_text().splitlines()
    start = lines.index(SITE_OPENER) + 1
    end = lines.index("}", start)  # the site block closes at column 0
    body = [ln.strip() for ln in lines[start:end]]
    return [ln for ln in body if ln and not ln.startswith("#")]


def _header_blocks(site: list[str]) -> list[list[str]]:
    blocks, current = [], None
    for ln in site:
        if current is None and re.fullmatch(r"header\s*\{", ln):
            current = []
        elif current is not None and ln == "}":
            blocks.append(current)
            current = None
        elif current is not None:
            current.append(ln)
    return blocks


def _field(name: str) -> str:
    (block,) = _header_blocks(_public_site_lines())
    (line,) = [ln for ln in block if ln.split(" ", 1)[0] == name]
    return line.split(" ", 1)[1].strip('"')


def _csp() -> dict[str, list[str]]:
    directives = {}
    for part in _field(CSP_RO).split(";"):
        words = part.split()
        if words:
            assert words[0] not in directives, f"{words[0]} given twice"
            directives[words[0]] = words[1:]
    return directives


def test_one_header_block_with_these_four_operations():
    site = _public_site_lines()
    assert not [ln for ln in site if re.match(r"header\s+\S", ln) and not ln.endswith("{")], (
        "a one-line header directive would run immediately and miss proxied responses"
    )
    (block,) = _header_blocks(site)
    assert [ln.split(" ", 1)[0] for ln in block] == [
        "-Server",
        "Strict-Transport-Security",
        "X-Content-Type-Options",
        CSP_RO,
    ]
    assert _field("X-Content-Type-Options") == "nosniff"


def test_hsts_is_for_this_host_only_and_one_year():
    value = _field("Strict-Transport-Security")
    assert "includesubdomains" not in value.lower()
    assert "preload" not in value.lower()
    assert re.fullmatch(r"max-age=(\d+)", value), value
    assert int(value.split("=")[1]) == 365 * 24 * 3600


def test_csp_sources_are_self_or_the_schemes_the_exporters_need():
    csp = _csp()
    assert csp["default-src"] == ["'self'"]
    assert csp["object-src"] == ["'none'"]
    assert csp["frame-ancestors"] == ["'none'"]
    assert csp["base-uri"] == ["'self'"] and csp["form-action"] == ["'self'"]
    assert csp["img-src"] == ["'self'", "data:", "blob:"]
    for name, sources in csp.items():
        for s in sources:
            assert s.startswith("'") or s in ("data:", "blob:"), f"{name} names a host: {s}"
            assert s not in ("'unsafe-inline'", "'unsafe-eval'"), f"{name} allows {s}"
    assert "report-uri" not in csp and "report-to" not in csp  # console only, no endpoint


def test_wasm_keyword_matches_the_kernel_that_needs_it():
    src = (REPO / "services/webui-frontend/src/lib/sim/bb84Wasm.ts").read_text()
    uses_wasm = "WebAssembly.instantiate" in src
    assert ("'wasm-unsafe-eval'" in _csp()["script-src"]) == uses_wasm
    assert _csp()["script-src"][0] == "'self'"


def test_style_hash_is_the_one_inline_style_block_of_index_html():
    html = (REPO / "services/webui-frontend/index.html").read_text(encoding="utf-8")
    blocks = re.findall(r"<style>(.*?)</style>", html, flags=re.S)
    assert len(blocks) == 1, "one inline <style> block; hash each one if that changes"
    digest = base64.b64encode(hashlib.sha256(blocks[0].encode("utf-8")).digest()).decode()
    assert _csp()["style-src"] == ["'self'", f"'sha256-{digest}'"]


def test_the_site_still_proxies_only_to_the_frontend():
    site = _public_site_lines()
    assert [ln for ln in site if ln.startswith("reverse_proxy")] == ["reverse_proxy webui-frontend:80"]
