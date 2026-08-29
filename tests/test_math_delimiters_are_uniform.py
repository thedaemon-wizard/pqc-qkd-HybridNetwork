"""Inline math must use the code-span form, so Markdown cannot eat it first.

GitHub renders both ``$x$`` and ``$`x`$``. They are not equivalent. The bare
form is plain text to the Markdown parser, which runs BEFORE the math renderer
and is free to interpret what it finds:

    $\\varepsilon_{\\text{sec}} = 21\\varepsilon$

Two underscores, so a parser looking for emphasis can pair them and hand the
math renderer a string with `<em>` in the middle. The backtick form is a code
span; nothing inside it is markup.

The docs mixed the two -- `docs/keyrate.md` had 64 bare against 23 backticked,
and `docs/references.md` used both delimiters in a single table row:

    | ... | $12.7 \\pm 10.3$ bit/s | $`13.3 \\pm 9.6\\,\\%`$ |

That row is the tell. Nobody chooses two conventions for two cells of one row;
the file simply drifted, and no check existed to notice. Converted 2026-08-29.

SCOPE. Only inline math is governed. Display math lives in ```math fences and
is untouched -- fences are stripped before scanning. Inline code spans are
stripped too, so a literal `$5` inside backticks is not a finding.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DOCS = sorted((ROOT / "docs").glob("*.md"))

FENCE = re.compile(r"```.*?```", re.S)
TICK_MATH = re.compile(r"\$`[^`]*`\$")
# A code span's fence is a RUN of backticks, and the run length must match to
# close it. `` `[^`\n]*` `` handles only the single-backtick case, so a span
# written ``like $this$`` -- which is how you quote a literal backtick, and how
# keyrate.md quotes the bad delimiter it is warning against -- leaked its
# contents into the scan and the file failed its own rule.
CODE_SPAN = re.compile(r"(`+)[^\n]*?\1")
BARE_MATH = re.compile(r"\$[^$\n]+\$")


def _scannable(text: str) -> str:
    """Strip everything a bare-`$` scan must not look inside.

    Order matters: fenced blocks, then the correct `$`...`$` form, then any
    remaining inline code. Doing code spans first would shred `$`x`$` into a
    leftover pair of dollars and produce a false positive on correct text.
    """
    text = FENCE.sub("", text)
    text = TICK_MATH.sub("", text)
    return CODE_SPAN.sub("", text)


def test_there_are_docs_to_check() -> None:
    # A glob that matches nothing makes every parametrised test below vanish
    # and the file pass by having no work to do.
    assert len(DOCS) >= 5, f"docs/*.md found only {len(DOCS)} files"


@pytest.mark.parametrize("path", DOCS, ids=lambda p: p.name)
def test_no_bare_dollar_inline_math(path: Path) -> None:
    if path.name == Path(__file__).name:      # not reachable; documents intent
        pytest.skip("self")
    offenders = BARE_MATH.findall(_scannable(path.read_text(encoding="utf-8")))
    assert not offenders, (
        f"{path.relative_to(ROOT)} uses bare $...$ inline math; write it as "
        f"$`...`$ so Markdown cannot parse the LaTeX:\n  "
        + "\n  ".join(offenders[:12])
        + (f"\n  ... and {len(offenders) - 12} more" if len(offenders) > 12 else "")
    )


def test_the_scan_can_actually_fail() -> None:
    """Guard against _scannable() stripping so much that nothing is ever seen.

    Every assertion above passes on a function that returns "". This one does
    not.
    """
    planted = "Prose with $e_0 = \\tfrac12$ inline.\n"
    assert BARE_MATH.findall(_scannable(planted)), \
        "the detector cannot see a bare $...$ at all"


def test_the_scan_does_not_flag_the_correct_form() -> None:
    assert not BARE_MATH.findall(_scannable("Prose with $`e_0 = \\tfrac12`$ inline.\n"))


def test_the_scan_ignores_fenced_display_math() -> None:
    fenced = "```math\nX + Y > Z\n```\nand $`x`$ after.\n"
    assert not BARE_MATH.findall(_scannable(fenced))


def test_the_scan_ignores_dollars_inside_code_spans() -> None:
    assert not BARE_MATH.findall(_scannable("Run `export FOO=$BAR` then `$PATH` again.\n"))


def test_keyrate_documents_the_convention() -> None:
    # If the rule is enforced by a test but written down nowhere, the next
    # author learns it from a red CI run instead of from the file.
    text = (ROOT / "docs" / "keyrate.md").read_text(encoding="utf-8")
    assert "Math delimiters" in text
    assert Path(__file__).name in text, (
        "keyrate.md should name the test that enforces the convention"
    )


def test_the_scan_handles_multi_backtick_code_spans() -> None:
    # The case that made this file fail on itself: keyrate.md quotes the bad
    # delimiter, and quoting a backtick needs a longer fence.
    text = "Write ``$x$`` as ``$`x`$`` instead.\n"
    assert not BARE_MATH.findall(_scannable(text)), \
        "a double-backtick code span leaked its contents into the scan"
