"""A summary statistic must carry the name of what it summarised.

`tools/compare_to_paper.py` reads columns 0 and 1 of every CSV under the paper
supplementary and summarises column 1. Different files hold different things
there. The output recorded only `mean`, `stddev`, `min`, `max` -- no indication
of which quantity, in which unit.

So this happened. In `rosenpass-scalability/results/experiment-summary.csv` the
columns are `peer_count` and `avg_cpu_percent`; that file has no handshake-time
column at all. The tool reported `mean: 11.93`. docs/phases.md then read it as a
handshake time and stated:

    "rosenpass-scalability experiment-summary.csv mean handshake time is within
     +/-15 % of the paper's 10.27 s @ 10 nodes."

A mean CPU **percentage** compared against a **time in seconds**, at a peer
count (10) that does not appear in the file -- its rows are 1, 500, 1000, 2500,
5000 -- and against an `ours` entry of `{"n": 0}`, because
`benchmarks/results/handshake_age.csv` has never been produced. The "agreement"
was a coincidence between two numbers of similar magnitude in different units.

Nothing in the build could contradict it: the mean was correctly computed, the
JSON was well-formed, and the sentence in the docs was the only place the two
were joined.

The tests below pin the fix so the units cannot go missing again.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
COMPARISON = ROOT / "benchmarks" / "results" / "paper_comparison.json"
SUMMARY_CSV = (
    ROOT / "submodules" / "qkd-pqc-paper-supplementary"
    / "rosenpass-scalability" / "results" / "experiment-summary.csv"
)


def _comparison() -> dict:
    if not COMPARISON.is_file():
        pytest.skip("paper_comparison.json not generated")
    return json.loads(COMPARISON.read_text(encoding="utf-8"))


def test_every_baseline_names_the_column_it_averaged():
    """`mean` without a column name is a number waiting to be misread."""
    baselines = _comparison().get("paper_baselines", [])
    assert baselines, "no baselines recorded; the tool found no CSVs"

    missing = [
        b.get("path", "?") for b in baselines
        if "mean" in b and not b.get("y_column")
    ]
    assert not missing, (
        "these summaries report a mean without saying which column it came "
        "from, which is exactly how a CPU percentage was read as a handshake "
        "time:\n  " + "\n  ".join(missing)
    )


def test_the_column_that_was_misread_is_named_and_is_not_a_time():
    """The specific case, pinned by name rather than by count."""
    baselines = _comparison().get("paper_baselines", [])
    match = [b for b in baselines if b.get("name") == "experiment-summary"]
    if not match:
        pytest.skip("supplementary submodule not checked out")
    got = match[0]

    assert got["y_column"] == "avg_cpu_percent", (
        f"expected the summarised column to be avg_cpu_percent, got "
        f"{got.get('y_column')!r}. If upstream changed the file, re-read it "
        "before any document describes this mean as a duration."
    )
    # Nothing in that column is seconds. Stated as an assertion so a future
    # edit that reintroduces a time reading has to argue with a test.
    assert "sec" not in got["y_column"] and "time" not in got["y_column"]


def test_an_absent_measurement_is_distinguishable_from_a_measured_zero():
    """`n == 0` must say WHY, not just be zero.

    The +/-15 % sentence was written against `{"name": "ours", "n": 0}` -- a
    shape that reads as a result rather than as its absence.
    """
    ours = _comparison().get("ours", {})
    if ours.get("n"):
        return  # a real measurement exists; nothing to guard here
    assert ours.get("note"), (
        "`ours` has no rows but does not say so. 'we did not measure' and "
        "'we measured zero' must not share a representation."
    )


def test_the_source_csv_still_has_no_handshake_time_column():
    """Derived from the file, not from memory -- if upstream adds one, fail."""
    if not SUMMARY_CSV.is_file():
        pytest.skip("supplementary submodule not checked out")
    header = SUMMARY_CSV.read_text(encoding="utf-8").splitlines()[0].split(",")
    lowered = [h.strip().lower() for h in header]
    timeish = [h for h in lowered if "time" in h or h.endswith("_s") or "sec" in h]
    assert not timeish, (
        f"experiment-summary.csv now has time-like columns {timeish}. The "
        "documents that used to compare its mean to a handshake time were "
        "wrong about THIS file; re-check them against the new columns rather "
        "than assuming the old sentence became true."
    )
    assert lowered[:2] == ["peer_count", "avg_cpu_percent"]
