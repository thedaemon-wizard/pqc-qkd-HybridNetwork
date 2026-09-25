"""index.html is revalidated on every load; hashed bundles are cached for a year.

With no Cache-Control at all, browsers cached index.html heuristically and kept
running the previous bundle after a deploy. On 2026-09-16 that produced a false
defect report against /paper-flow (the Step button "did nothing" in a tab still
executing the old build). These checks pin the three nginx locations that
prevent it, and the one that stops a missing bundle being answered with
index.html under an immutable header.
"""
from __future__ import annotations

import pathlib
import re

NGINX = (pathlib.Path(__file__).resolve().parents[1]
         / "services" / "webui-frontend" / "nginx.conf")


def _blocks() -> dict[str, str]:
    """`location` selector -> body, with comments stripped."""
    text = "\n".join(line.split("#", 1)[0] for line in NGINX.read_text().splitlines())
    return {m.group(1).strip(): m.group(2)
            for m in re.finditer(r"location\s+([^{]+)\{([^}]*)\}", text)}


def test_the_spa_shell_is_revalidated():
    blocks = _blocks()
    for selector in ("/", "= /index.html"):
        assert selector in blocks, f"missing `location {selector}`"
        assert re.search(r'add_header\s+Cache-Control\s+"no-cache"\s+always;',
                         blocks[selector]), selector


def test_hashed_assets_are_immutable_and_never_fall_back():
    body = _blocks()["/assets/"]
    assert re.search(r"max-age=31536000", body) and "immutable" in body
    assert re.search(r"try_files\s+\$uri\s+=404;", body), (
        "a missing bundle must 404, not return index.html marked immutable")
    # Measured before this line existed: with `always`, the 404 for a missing
    # bundle carried `max-age=31536000, immutable` too.
    assert not re.search(r"immutable\"?\s+always", body), (
        "`always` puts the one-year header on the 404 as well")


def test_every_emitted_asset_lives_under_assets():
    """The immutable rule only helps if Vite actually emits hashed files there."""
    vite = (NGINX.parent / "vite.config.ts").read_text()
    assert "assetsDir" not in vite or re.search(r"assetsDir:\s*['\"]assets['\"]", vite)
