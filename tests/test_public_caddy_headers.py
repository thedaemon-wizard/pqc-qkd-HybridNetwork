"""The public Caddy site sends HSTS and nosniff, and still drops nginx's Server header.

All three are in one `header` block of the public site in deploy/Caddyfile.
Because the block deletes a field, Caddy defers every operation in it until the
response is written ("header operations are performed immediately unless any of
the headers are being deleted", Caddy's header directive docs), so the two added
fields also reach the responses proxied from webui-frontend. A second, separate
`header` line that only sets fields would run immediately instead, which is why
the block is checked as a whole.

HSTS is for this hostname only and for one year: no includeSubDomains, no
preload (RFC 6797; sending max-age=0 undoes it).
"""
from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SITE_OPENER = "{$PUBLIC_HOST} {"


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


def test_one_header_block_drops_server_and_adds_hsts_and_nosniff():
    site = _public_site_lines()
    assert not [ln for ln in site if re.match(r"header\s+\S", ln) and not ln.endswith("{")], (
        "a one-line header directive would run immediately and miss proxied responses"
    )
    assert _header_blocks(site) == [[
        "-Server",
        'Strict-Transport-Security "max-age=31536000"',
        'X-Content-Type-Options "nosniff"',
    ]]


def test_hsts_is_for_this_host_only_and_one_year():
    (block,) = _header_blocks(_public_site_lines())
    (hsts,) = [ln for ln in block if ln.startswith("Strict-Transport-Security")]
    value = hsts.split(" ", 1)[1].strip('"')
    assert "includesubdomains" not in value.lower()
    assert "preload" not in value.lower()
    assert re.fullmatch(r"max-age=(\d+)", value), value
    assert int(value.split("=")[1]) == 365 * 24 * 3600


def test_the_site_still_proxies_only_to_the_frontend():
    site = _public_site_lines()
    assert [ln for ln in site if ln.startswith("reverse_proxy")] == ["reverse_proxy webui-frontend:80"]
