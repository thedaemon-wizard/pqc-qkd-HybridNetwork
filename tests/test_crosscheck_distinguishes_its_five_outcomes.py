"""The key-rate cross-check must not answer five questions with one `false`.

`/sim/keyrate/crosscheck` used to return::

    same_order_of_magnitude = (tno_rate is not None and ours > 0
                               and 0.1 <= (tno_rate / ours) <= 10.0)

Five distinct outcomes collapsed onto `false`, and three of them ALSO produced
`relative_delta: null`, so the payload could not distinguish them either:

===========================  ==============  ==============  =====  ==========
outcome                      ours            tno_rate        bool   rel_delta
===========================  ==============  ==============  =====  ==========
engine never ran             1.2e-02         None            false  null
ran, disagreed by 1000x      1.2e-02         12.3            false  999.0
ran, returned 0.0            1.2e-02         0.0             false  null  (*)
BOTH returned 0.0            0.0             0.0             false  null
ours 0, TNO tiny             0.0             1e-09           false  null
===========================  ==============  ==============  =====  ==========

(*) the `if tno_rate and ours > 0` guard used truthiness, so a genuine TNO
output of 0.0 serialised byte-identically to the engine never running.

The fourth row is the inversion that motivated this file. Two independent
implementations concluding that no extractable key exists is the strongest
agreement they can reach, and /verify rendered it as "review" -- the same word
as "the optimiser is not installed".

It is not hypothetical. With the shipped config the closed-form rate crosses
zero at L = 253.51 km (QBER 6.60 %), and `physical.link_length_km` is an
unbounded editable field on /physics. Nothing in the build could have caught it:
the bool was never asserted on, and "review" is a plausible thing for a
verification page to say.

These tests drive `_crosscheck_verdict` directly rather than the HTTP route,
because the states differ only in the two floats -- reaching all five through
the endpoint would mean five TNO stubs to test one pure function.
"""
from __future__ import annotations

import pathlib

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
MAIN_PY = REPO / "services" / "bb84-kme" / "app" / "main.py"


@pytest.fixture(scope="module")
def mod():
    """Load main.py without importing the package (FastAPI app + heavy deps)."""
    src = MAIN_PY.read_text(encoding="utf-8")
    ns: dict = {}
    # Execute only the verdict helper and its constants: the rest of main.py
    # pulls in fastapi and the backends, which this test has no use for.
    start = src.index("CROSSCHECK_AGREE")
    end = src.index('@app.get("/sim/keyrate/crosscheck")')
    exec(compile(src[start:end], str(MAIN_PY), "exec"), ns)  # noqa: S102
    if "_crosscheck_verdict" not in ns:
        pytest.fail("_crosscheck_verdict is not defined between the constants "
                    "and the crosscheck route -- has main.py been restructured?")
    return ns


# --------------------------------------------------------------------------
# The five states, each named and each distinct.
# --------------------------------------------------------------------------

CASES = [
    # (ours, tno_rate, expected verdict, why this case exists)
    (1.23e-02, None,    "engine_unavailable",
     "TNO package missing or compute raised -- an absent measurement"),
    (1.23e-02, 1.30e-02, "agree",
     "both predict a key, ratio 1.06, within [0.1, 10]"),
    (1.23e-02, 12.334,   "disagree",
     "both predict a key, ratio 1003 -- a real disagreement"),
    (1.23e-02, 0.0,      "one_side_zero",
     "TNO ran and returned exactly 0 while ours did not"),
    (0.0,      1.0e-09,  "one_side_zero",
     "ours 0 and TNO nonzero -- the mirror of the row above"),
    (0.0,      0.0,      "neither_predicts_a_key",
     "the inversion: complete agreement, previously rendered 'review'"),
]


@pytest.mark.parametrize("ours,tno,expected,why", CASES,
                         ids=[c[2] + "-" + c[3][:24] for c in CASES])
def test_each_outcome_gets_its_own_verdict(mod, ours, tno, expected, why):
    assert mod["_crosscheck_verdict"](ours, tno) == expected, why


def test_the_five_verdicts_are_five_distinct_strings(mod):
    """The point of the change: no two states share a value."""
    verdicts = {mod["_crosscheck_verdict"](o, t) for o, t, _, _ in CASES}
    assert len(verdicts) == 5, verdicts          # 6 cases, 5 distinct verdicts
    names = {v for k, v in mod.items() if k.startswith("CROSSCHECK_")}
    assert len(names) == 5, f"a constant was added or removed: {names}"
    assert verdicts <= names, "a verdict was returned that has no named constant"


def test_both_zero_is_not_reported_as_disagreement(mod):
    """The regression this file exists for.

    Under the old bool this returned `false`, which /verify printed as "review".
    """
    assert mod["_crosscheck_verdict"](0.0, 0.0) == "neither_predicts_a_key"
    assert mod["_crosscheck_verdict"](0.0, 0.0) != mod["CROSSCHECK_DISAGREE"]


def test_both_zero_is_not_reported_as_agreement_either(mod):
    """Nor is it laundered into the ratio bucket.

    "Same order of magnitude" is undefined for 0/0. Returning AGREE would be a
    different false claim -- it would assert a ratio test that never ran.
    """
    assert mod["_crosscheck_verdict"](0.0, 0.0) != mod["CROSSCHECK_AGREE"]


def test_zero_cases_are_decided_before_the_ratio(mod):
    """`tno_rate / ours` raises on ours == 0. Order is load-bearing."""
    for tno in (0.0, 1e-30, 1.0, 1e30):
        assert mod["_crosscheck_verdict"](0.0, tno) in (
            "neither_predicts_a_key", "one_side_zero")


@pytest.mark.parametrize("ratio,expected", [
    (0.05, "disagree"), (0.1, "agree"), (1.0, "agree"),
    (10.0, "agree"), (10.001, "disagree"),
])
def test_the_ratio_boundaries_are_inclusive_as_before(mod, ratio, expected):
    """The one behaviour that must NOT change: the surviving ratio test."""
    ours = 1.0e-06
    assert mod["_crosscheck_verdict"](ours, ours * ratio) == expected


# --------------------------------------------------------------------------
# The endpoint and its readers.
# --------------------------------------------------------------------------

def test_the_collapsing_bool_is_gone_from_the_payload():
    """A rename only helps if the old field stops being emitted."""
    src = MAIN_PY.read_text(encoding="utf-8")
    emitted = [ln for ln in src.splitlines()
               if '"same_order_of_magnitude"' in ln]
    assert emitted == [], f"the old key is still in the response: {emitted}"


def test_relative_delta_uses_is_not_none_not_truthiness():
    """A TNO rate of exactly 0.0 must not serialise as "engine never ran"."""
    src = MAIN_PY.read_text(encoding="utf-8")
    assert "if (tno_rate is not None and ours > 0)" in src, (
        "the truthiness guard `if (tno_rate and ours > 0)` is back -- a genuine "
        "TNO output of 0.0 would again be indistinguishable from a missing one")


def test_no_frontend_file_still_reads_the_old_field():
    """The bool had exactly three readers. All three must have moved."""
    stale = []
    for f in (REPO / "services" / "webui-frontend" / "src").rglob("*.ts*"):
        # Property access, not the identifier: crosscheckVerdict.ts names the
        # removed field in its header comment, which is the record of why it
        # was removed and must survive.
        if ".same_order_of_magnitude" in f.read_text(encoding="utf-8"):
            stale.append(str(f.relative_to(REPO)))
    assert stale == [], f"still reading the removed field: {stale}"


def test_the_checklist_row_was_updated_too():
    """4.7.4 asserted `same_order_of_magnitude: true` as its pass criterion."""
    txt = (REPO / "VERIFICATION_CHECKLIST.md").read_text(encoding="utf-8")
    assert "same_order_of_magnitude" not in txt, (
        "VERIFICATION_CHECKLIST.md still cites the removed field as a pass "
        "criterion, so the checklist can no longer be executed as written")
