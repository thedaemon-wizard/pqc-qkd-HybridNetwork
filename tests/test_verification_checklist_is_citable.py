"""`VERIFICATION_CHECKLIST.md` row IDs are a citation surface, so they must hold.

`docs/references.md`, `docs/deployment-economics.md`, `services/arnika-vici/README.md`
and `docs/paper_mapping.md` all point at rows by number. Three defects had
accumulated, all of them invisible to a reader of the diff that introduced them:

  * duplicate IDs -- 4.2.4, 4.6.4 and 4.6.5 each existed twice, so "see 4.6.4"
    identified nothing. Easy to introduce, because appending to a section means
    knowing the last ID of a table whose end may be a hundred lines above the
    insertion point.
  * out-of-order IDs -- section 7 read 7.1, 7.0, 7.0b, 7.0c, 7.2, because new
    rows were prepended with a number lower than the row above them.
  * silently dropped cells -- three rows carried a third cell under a
    two-column header. GFM discards cells beyond the header width, so their
    verification commands rendered nowhere. Nothing in the source looks wrong;
    the loss is only visible in the rendered page.

The third is the reason this is a test and not a review habit.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

CHECKLIST = Path(__file__).resolve().parents[1] / "VERIFICATION_CHECKLIST.md"

# `4.2.1`, `2.8b`, `4.4b.4`, `7.10`
ROW_ID = re.compile(r"^\d+[a-z]?(\.\d+[a-z]?)*$")
DELIMITER = re.compile(r"^[-: ]+$")


def _cells(line: str) -> list[str]:
    """Split a table row on unescaped pipes, as GFM does.

    The leading and trailing pipes are both optional in GFM, so they are
    stripped rather than required -- being stricter than the renderer would
    make this test disagree with the rendered page, which is the thing it is
    supposed to be measuring.
    """
    body = line.strip()
    body = body.removeprefix("|").removesuffix("|")
    return [c.strip() for c in re.split(r"(?<!\\)\|", body)]


def _tables():
    """Yield (header_width, [(line_number, cells)]) for each table in the file."""
    lines = CHECKLIST.read_text(encoding="utf-8").splitlines()
    header_width = None
    rows: list[tuple[int, list[str]]] = []
    fenced = False
    for n, line in enumerate(lines, 1):
        s = line.strip()
        if s.startswith("```"):
            fenced = not fenced
        # ASCII diagrams inside code fences use box-drawing, not pipes, but a
        # fence is skipped anyway so nothing inside one can be read as a row.
        if fenced or not s.startswith("|"):
            if header_width is not None:
                yield header_width, rows
            header_width, rows = None, []
            continue
        cells = _cells(line)
        if all(DELIMITER.fullmatch(c) or not c for c in cells):
            continue  # |---|---| delimiter
        if header_width is None:
            header_width = len(cells)
            continue
        rows.append((n, cells))
    if header_width is not None:
        yield header_width, rows


def _ids():
    for _, rows in _tables():
        for n, cells in rows:
            if cells and ROW_ID.fullmatch(cells[0]):
                yield n, cells[0]


def _sort_key(row_id: str):
    """`2.8b` sorts after `2.8` and before `2.9`; `7.10` after `7.9`."""
    return tuple(
        (int(m.group(1)), m.group(2))
        for m in (re.fullmatch(r"(\d+)([a-z]?)", part) for part in row_id.split("."))
    )


def test_no_row_id_is_used_twice():
    seen: dict[str, int] = {}
    dupes = []
    for n, row_id in _ids():
        if row_id in seen:
            dupes.append(f"{row_id} at lines {seen[row_id]} and {n}")
        seen[row_id] = n
    assert not dupes, "duplicate row IDs make a row uncitable:\n  " + "\n  ".join(dupes)


def test_row_ids_ascend_within_each_table():
    out_of_order = []
    for _, rows in _tables():
        prev_id = prev_line = None
        for n, cells in rows:
            if not (cells and ROW_ID.fullmatch(cells[0])):
                continue
            if prev_id is not None and _sort_key(cells[0]) <= _sort_key(prev_id):
                out_of_order.append(f"line {n}: {cells[0]} follows {prev_id} (line {prev_line})")
            prev_id, prev_line = cells[0], n
    assert not out_of_order, (
        "row IDs must ascend in document order:\n  " + "\n  ".join(out_of_order)
    )


def test_no_row_has_cells_the_renderer_will_drop():
    dropped = []
    for header_width, rows in _tables():
        for n, cells in rows:
            if len(cells) > header_width:
                dropped.append(
                    f"line {n}: {len(cells)} cells under a {header_width}-column "
                    f"header, so GFM drops {cells[header_width:]!r}"
                )
    assert not dropped, (
        "these cells render nowhere -- widen the header row:\n  " + "\n  ".join(dropped)
    )


@pytest.mark.parametrize("cited", ["4.6.1", "4.6.2", "4.6.3", "7.1"])
def test_ids_cited_by_other_documents_still_exist(cited):
    """Rows other files point at by number. Renumbering must not orphan them."""
    assert cited in {row_id for _, row_id in _ids()}, (
        f"{cited} is cited elsewhere in the repository but no longer exists"
    )


def test_every_screenshot_a_document_names_actually_exists():
    """Prose naming a file is a claim about the repository too.

    `docs/phases.md` and `docs/IMAGE1_VPN_SCOPE.md` cited three captures --
    e2e-v2-idle.png, e2e-v2-phase1.png, e2e-v3-export-toolbar-top.png -- that
    were never committed. The Markdown link checker in checklist row 7.6 could
    not see them: they were written as inline code spans, not links, so nothing
    resolved them and the claim read as verified evidence.
    """
    import re
    import subprocess

    root = CHECKLIST.parent
    shots = root / "docs" / "images" / "screenshots"
    present = {p.name for p in shots.iterdir()} if shots.is_dir() else set()

    tracked = subprocess.run(
        ["git", "ls-files", "*.md"], cwd=root, capture_output=True, text=True, check=True,
    ).stdout.split()

    missing = []
    for rel in tracked:
        if rel.startswith("submodules/"):
            continue
        text = (root / rel).read_text(encoding="utf-8", errors="replace")
        for name in re.findall(r"docs/images/screenshots/([A-Za-z0-9_.-]+\.png)", text):
            if name not in present:
                missing.append(f"{rel} names docs/images/screenshots/{name}")

    assert not missing, "documents cite screenshots that do not exist:\n  " + "\n  ".join(missing)


def test_no_markdown_table_anywhere_drops_cells():
    """The same GFM truncation, across every tracked document.

    This check began life scoped to VERIFICATION_CHECKLIST.md, and then I
    introduced exactly the defect it exists to catch -- a six-cell row under a
    five-column header -- in docs/THIRD_PARTY_NOTICES.md, which it was not
    watching. A guard that only covers the file where the bug was first found
    is a guard that catches the bug once.

    Cells past the header width are discarded by the renderer, so the source
    looks fine and the published page silently loses content.
    """
    import re
    import subprocess

    root = CHECKLIST.parent
    files = subprocess.run(
        ["git", "ls-files", "*.md"], cwd=root, capture_output=True, text=True, check=True,
    ).stdout.split()

    dropped = []
    for rel in files:
        if rel.startswith("submodules/"):
            continue
        lines = (root / rel).read_text(encoding="utf-8", errors="replace").splitlines()
        header_width = None
        fenced = False
        for n, line in enumerate(lines, 1):
            s = line.strip()
            if s.startswith("```"):
                fenced = not fenced
            if fenced or not (s.startswith("|") and s.endswith("|")):
                header_width = None
                continue
            cells = [c.strip() for c in re.split(r"(?<!\\)\|", s[1:-1])]
            if all(DELIMITER.fullmatch(c) or not c for c in cells):
                continue
            if header_width is None:
                header_width = len(cells)
                continue
            if len(cells) > header_width:
                dropped.append(
                    f"{rel}:{n}: {len(cells)} cells under a {header_width}-column header"
                )

    assert not dropped, (
        "these table cells render nowhere:\n  " + "\n  ".join(dropped)
    )


def test_the_header_table_matches_the_actual_row_counts():
    """The "Where the work is" table states counts that are easy to invalidate.

    Adding a row anywhere silently falsifies it, and a stale count in a document
    whose purpose is accuracy is worse than no count. So it is recomputed here
    rather than trusted.

    The automation heuristic is the same one used to write the table: a row is
    machine-checked if it names pytest, vitest, make, or a CI job.
    """
    import re

    text = CHECKLIST.read_text(encoding="utf-8")
    auto_pat = re.compile(r"pytest|npx vitest|CI `|CI job|`make ")

    actual: dict[str, dict[str, int]] = {}
    section = None
    for line in text.splitlines():
        m = re.match(r"^## (\d+)\.", line)
        if m:
            section = m.group(1)
            actual[section] = {"rows": 0, "auto": 0}
        if section and re.match(r"^\| \d", line):
            actual[section]["rows"] += 1
            if auto_pat.search(line):
                actual[section]["auto"] += 1

    # `| 4 | Browser, every page | 111 | 2 | 109 |`
    claimed = {
        m.group(1): {"rows": int(m.group(2)), "auto": int(m.group(3)), "manual": int(m.group(4))}
        for m in re.finditer(
            r"^\| (\d) \| [^|]+ \| \*{0,2}(\d+)\*{0,2} \| \*{0,2}(\d+)\*{0,2} \| \*{0,2}(\d+)\*{0,2} \|$",
            text, re.M)
    }
    assert claimed, "the 'Where the work is' table is no longer parseable"
    assert set(claimed) == set(actual), (
        f"header table covers sections {sorted(claimed)} but the document has "
        f"{sorted(actual)}"
    )

    wrong = []
    for sec, c in claimed.items():
        a = actual[sec]
        if (c["rows"], c["auto"], c["manual"]) != (a["rows"], a["auto"], a["rows"] - a["auto"]):
            wrong.append(
                f"section {sec}: table says {c['rows']}/{c['auto']}/{c['manual']} "
                f"(rows/auto/manual), actual is "
                f"{a['rows']}/{a['auto']}/{a['rows'] - a['auto']}"
            )
    assert not wrong, "the header table has drifted from the rows:\n  " + "\n  ".join(wrong)

    total_rows = sum(a["rows"] for a in actual.values())
    total_auto = sum(a["auto"] for a in actual.values())
    prose = re.search(r"(\d+) rows, of which \*\*(\d+) are machine-checked and (\d+) are not\*\*", text)
    assert prose, "the totals sentence above the table is gone or reworded"
    assert (int(prose.group(1)), int(prose.group(2)), int(prose.group(3))) == (
        total_rows, total_auto, total_rows - total_auto
    ), (
        f"totals sentence says {prose.group(1)}/{prose.group(2)}/{prose.group(3)}, "
        f"actual is {total_rows}/{total_auto}/{total_rows - total_auto}"
    )
