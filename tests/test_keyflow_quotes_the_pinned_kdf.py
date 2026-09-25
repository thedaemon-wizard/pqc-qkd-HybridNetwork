"""The /keyflow page quotes arnika's key derivation; the quote must be real.

`services/webui-frontend/src/pages/KeyFlow.tsx` shows a <pre> block of Go under
the citation `submodules/arnika/kdf/kdf.go`: the combined-input construction,
the `hkdf.New(...)` call and the read of the 32-byte output. A quotation under
a file citation is a claim about that file, and the one thing a reader cannot
check from the page is whether the pinned file still says it.

So every Go line in the block must appear, verbatim apart from indentation, in
the pinned kdf.go, and in the same order. Two things in the block are not
quotations and are handled by name rather than by a looser match:

  * the elision `{ ... }` closing the `io.ReadFull` line, which stands for the
    error branch the page leaves out: the text before it must still be a whole
    line of the file;
  * comment lines the page adds to explain the code (PAGE_OWN_COMMENTS). Every
    other comment line is a quotation and is checked like code.

`...` inside a line is not an elision: `append(combined, qkdKey...)` is Go's
variadic spread, so only the trailing `{ ... }` form is treated as one.

Self-skips without the arnika submodule; the CI `go` job checks it out.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "services" / "webui-frontend" / "src" / "pages" / "KeyFlow.tsx"
KDF_CITATION = "submodules/arnika/kdf/kdf.go"
KDF_GO = ROOT / KDF_CITATION

# Comment lines that are the page's own annotation, not text from kdf.go. Each
# must still be in the block (checked below), so this cannot go stale unseen.
PAGE_OWN_COMMENTS = frozenset({
    "// derivedKey becomes the WireGuard PSK for this rotation interval",
})

# The page's shorthand for an omitted block body, and what the file has there:
# `if cond { ... }` on the page is the line `if cond {` in the file.
ELIDED_BODY_SUFFIX = " { ... }"
OPENED_BODY_SUFFIX = " {"

# A <pre> element whose body is one JSX template literal: <pre ...>{`...`}</pre>
_PRE_TEMPLATE = re.compile(r"<pre\b[^>]*>\s*\{`(.*?)`\}\s*</pre>", re.DOTALL)


def _kdf_lines() -> list[str]:
    if not KDF_GO.is_file():
        pytest.skip(f"{KDF_CITATION} absent: the arnika submodule is not checked "
                    "out (git submodule update --init submodules/arnika)")
    return [ln.strip() for ln in KDF_GO.read_text(encoding="utf-8").splitlines()
            if ln.strip()]


def _quoted_block() -> str:
    src = PAGE.read_text(encoding="utf-8")
    blocks = [b for b in _PRE_TEMPLATE.findall(src) if "hkdf.New(" in b]
    assert len(blocks) == 1, (
        f"expected exactly one <pre> template literal quoting hkdf.New( in "
        f"{PAGE.relative_to(ROOT)}, found {len(blocks)}; the parser below "
        f"reads only that shape")
    block = blocks[0]
    # An interpolation or escape would make the rendered text differ from the
    # source text this test compares.
    assert "${" not in block and "\\" not in block, (
        "the quoted block uses template interpolation or escapes; compare the "
        "rendered text instead of the source")
    return block


def _as_file_line(line: str) -> str:
    """The text the file must contain for this quoted line."""
    if line.endswith(ELIDED_BODY_SUFFIX):
        return line[: -len(ELIDED_BODY_SUFFIX)] + OPENED_BODY_SUFFIX
    return line


def _quoted_go_lines() -> list[str]:
    lines = [ln.strip() for ln in _quoted_block().splitlines() if ln.strip()]
    return [_as_file_line(ln) for ln in lines if ln not in PAGE_OWN_COMMENTS]


def test_the_page_cites_the_file_this_test_reads():
    assert KDF_CITATION in PAGE.read_text(encoding="utf-8"), (
        f"KeyFlow.tsx no longer cites {KDF_CITATION}; point this test at the "
        f"file it does cite")


def test_the_page_quotes_the_hkdf_call():
    assert any("hkdf.New(" in ln for ln in _quoted_go_lines()), (
        "the block no longer quotes hkdf.New(")


def test_the_page_own_comments_are_still_in_the_block():
    lines = {ln.strip() for ln in _quoted_block().splitlines()}
    missing = sorted(PAGE_OWN_COMMENTS - lines)
    assert not missing, f"PAGE_OWN_COMMENTS lists lines the block no longer has: {missing}"


def test_every_quoted_line_is_in_the_pinned_kdf():
    file_lines = set(_kdf_lines())
    absent = [ln for ln in _quoted_go_lines() if ln not in file_lines]
    assert not absent, (
        f"/keyflow quotes these lines under {KDF_CITATION}, and the pinned file "
        f"does not contain them: {absent}")


def test_the_quoted_lines_keep_the_file_order():
    file_lines = _kdf_lines()
    pos = 0
    for ln in _quoted_go_lines():
        try:
            pos = file_lines.index(ln, pos) + 1
        except ValueError:
            pytest.fail(f"{ln!r} is out of order relative to {KDF_CITATION}, or "
                        f"absent (the previous test says which)")
