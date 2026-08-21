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
