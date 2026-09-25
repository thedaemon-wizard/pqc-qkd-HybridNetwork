"""docs/etsi004-binding.md describes the codes and transitions the spec file has.

The doc says the specification's facts live in one file,
`services/webui-frontend/src/lib/sim/etsi004SpecV211.json`, and then restates
two of them for the reader: the status codes (a table, one row per code, plus
the "0-8" range in prose) and the transition ids (the `T1` to `Tn` range every
response's `transition` field is drawn from, and the ids each status row cites
as the rules that return it). Restated facts drift from their source unless
something compares them, so this does:

  * the codes in the status table, and the range the prose gives, equal the
    file's status codes;
  * the transition range the doc gives equals the file's transition ids, and
    every T-id the doc names is one of them;
  * every T-id a status row cites can actually return that row's code. A
    transition carries its code in `status`, and some carry a second one for
    their other outcome (`status_on_timeout`, `status_otherwise`); any of them
    counts.

Reads both files only; nothing here imports the KME.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "etsi004-binding.md"
SPEC = ROOT / "services" / "webui-frontend" / "src" / "lib" / "sim" / "etsi004SpecV211.json"

# The header of the doc's status-code table; its rows follow until the first
# line that is not a table row.
STATUS_TABLE_HEADER = re.compile(r"^\|\s*Code\s*\|\s*Meaning\s*\|")
STATUS_ROW = re.compile(r"^\|\s*(\d+)\s*\|(.*)\|\s*$")
T_ID = re.compile(r"\bT(\d+)\b")
# "status codes 0-8" in prose (hyphen or en dash).
CODE_RANGE = re.compile(r"status codes (\d+)\s*[-–]\s*(\d+)")
# "`T1` to `T22`": the range of the `transition` field.
T_RANGE = re.compile(r"`T(\d+)` to `T(\d+)`")


def _spec() -> dict:
    return json.loads(SPEC.read_text(encoding="utf-8"))


def _doc() -> str:
    return DOC.read_text(encoding="utf-8")


def _spec_codes() -> set[int]:
    return {s["code"] for s in _spec()["status_codes"]}


def _spec_transitions() -> dict[str, dict]:
    return {t["id"]: t for t in _spec()["transitions"]}


def _codes_a_transition_can_return(t: dict) -> set[int]:
    return {v for k, v in t.items()
            if k.startswith("status") and isinstance(v, int) and not isinstance(v, bool)}


def _status_rows() -> dict[int, str]:
    lines = _doc().splitlines()
    starts = [i for i, ln in enumerate(lines) if STATUS_TABLE_HEADER.match(ln)]
    assert len(starts) == 1, (
        f"expected one '| Code | Meaning |' table in {DOC.name}, found {len(starts)}")
    rows: dict[int, str] = {}
    for ln in lines[starts[0] + 2:]:          # skip the header and its |---| rule
        if not ln.startswith("|"):
            break
        m = STATUS_ROW.match(ln)
        assert m, f"unparseable status-table row: {ln!r}"
        code = int(m.group(1))
        assert code not in rows, f"status {code} has two rows"
        rows[code] = m.group(2)
    assert rows, "the status table has no rows"
    return rows


def _t_ids(text: str) -> set[str]:
    return {f"T{n}" for n in T_ID.findall(text)}


def test_the_status_table_has_the_spec_codes():
    assert set(_status_rows()) == _spec_codes()


def test_the_prose_code_range_is_the_spec_codes():
    ranges = CODE_RANGE.findall(_doc())
    assert ranges, f"{DOC.name} no longer states the status-code range"
    for lo, hi in ranges:
        assert set(range(int(lo), int(hi) + 1)) == _spec_codes(), (
            f"{DOC.name} says 'status codes {lo}-{hi}'; the spec file has "
            f"{sorted(_spec_codes())}")


def test_the_transition_range_is_the_spec_ids():
    ranges = T_RANGE.findall(_doc())
    assert ranges, f"{DOC.name} no longer states the range of transition ids"
    for lo, hi in ranges:
        named = {f"T{n}" for n in range(int(lo), int(hi) + 1)}
        assert named == set(_spec_transitions()), (
            f"{DOC.name} gives T{lo} to T{hi}; the spec file has "
            f"{sorted(_spec_transitions(), key=lambda s: int(s[1:]))}")


def test_every_named_transition_exists():
    unknown = sorted(_t_ids(_doc()) - set(_spec_transitions()),
                     key=lambda s: int(s[1:]))
    assert not unknown, f"{DOC.name} names transitions the spec file lacks: {unknown}"


def test_each_status_row_cites_transitions_that_return_its_code():
    transitions = _spec_transitions()
    wrong = []
    for code, text in _status_rows().items():
        for tid in sorted(_t_ids(text), key=lambda s: int(s[1:])):
            t = transitions.get(tid)
            if t is not None and code not in _codes_a_transition_can_return(t):
                wrong.append(f"status {code} cites {tid}, which returns "
                             f"{sorted(_codes_a_transition_can_return(t))}")
    assert not wrong, "; ".join(wrong)
