"""A published metric must be produced by something.

Three of the five Prometheus metrics the KME declares were never incremented.
`/metrics` therefore served

    qkd_intercepted_photons_total 0.0     HELP "Photons intercepted by Eve"
    qkd_round_ms_count 0.0

while rounds were running, and `qkd_rounds_total` emitted no sample at all.
A scraper would have read a flat zero as "no photons were intercepted" rather
than "nothing counts them".

The comment that stood in for the work said so, in the manner these defects
usually do:

    # Counters are set by inc(); we observe deltas via attribute snapshots
    # (simplified: re-sync to current snapshot)

No line performed that. The HELP strings were a claim nothing in the build
could contradict.

Nothing scrapes them today -- no dashboard, no alert, no document reads
`/metrics` -- so the impact was latent. That is the reason to fix rather than
delete: the endpoint is offered, and an offered metric that is structurally
zero is worse than an absent one.
"""
from __future__ import annotations

import asyncio
import os
import pathlib
import sys
import types

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
os.environ.setdefault("QKD_PARAMS_FILE", str(ROOT / "config" / "qkd_params.yaml"))
os.environ.setdefault("LOG_DIR", "/tmp/pqcqkd-test-logs")
sys.path.insert(0, str(ROOT / "services" / "bb84-kme"))

prometheus_client = pytest.importorskip("prometheus_client")
from app import main as M  # noqa: E402
from app.keypool import PoolStats  # noqa: E402


class _FakePool:
    def __init__(self) -> None:
        self.st = PoolStats()

    def stats(self) -> PoolStats:
        return self.st


def _app() -> types.SimpleNamespace:
    return types.SimpleNamespace(state=types.SimpleNamespace(
        pool=_FakePool(), frame_subs=set(), metric_totals={}))


async def _one_tick(app) -> None:
    """Run the real loop briefly. Not a reimplementation of it."""
    task = asyncio.create_task(M._metrics_loop(app))
    await asyncio.sleep(0.05)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


def _value(name: str, labels: dict | None = None):
    return prometheus_client.REGISTRY.get_sample_value(name, labels or {})


# --------------------------------------------------------------------------
# The three that published nothing.
# --------------------------------------------------------------------------

def test_a_round_reaches_every_counter():
    app = _app()
    before_acc = _value("qkd_rounds_total", {"outcome": "accepted"}) or 0.0
    before_int = _value("qkd_intercepted_photons_total") or 0.0
    before_obs = _value("qkd_round_ms_count") or 0.0

    st = app.state.pool.st
    st.rounds_total, st.rounds_accepted = 3, 3
    st.intercepted_total, st.last_round_ms = 17, 250.0
    asyncio.run(_one_tick(app))

    assert (_value("qkd_rounds_total", {"outcome": "accepted"}) or 0.0) == before_acc + 3
    assert (_value("qkd_intercepted_photons_total") or 0.0) == before_int + 17
    assert (_value("qkd_round_ms_count") or 0.0) == before_obs + 1, (
        "the duration histogram took no observation for a completed round")


def test_an_aborted_round_is_labelled_separately():
    """`outcome` exists as a label; both values must actually be produced."""
    app = _app()
    before = _value("qkd_rounds_total", {"outcome": "aborted"}) or 0.0
    st = app.state.pool.st
    st.rounds_total, st.rounds_accepted, st.rounds_aborted = 2, 1, 1
    asyncio.run(_one_tick(app))
    assert (_value("qkd_rounds_total", {"outcome": "aborted"}) or 0.0) == before + 1


def test_counters_advance_by_the_delta_not_the_total():
    """The loop sees cumulative stats; a Counter takes increments.

    Adding the total each tick would multiply every value by the number of
    scrapes, which is the obvious wrong way to wire this.
    """
    app = _app()
    st = app.state.pool.st
    st.rounds_total, st.rounds_accepted = 5, 5
    asyncio.run(_one_tick(app))
    after_first = _value("qkd_rounds_total", {"outcome": "accepted"})

    asyncio.run(_one_tick(app))          # same totals, another tick
    assert _value("qkd_rounds_total", {"outcome": "accepted"}) == after_first, (
        "an idle tick advanced the counter, so the value scales with scrape "
        "count rather than with rounds")


def test_a_restart_does_not_make_a_counter_go_backwards():
    """Prometheus Counters must be monotonic.

    If the pool's totals reset (a restart, a stats reset), subtracting the
    previous baseline would produce a negative delta.
    """
    app = _app()
    st = app.state.pool.st
    st.rounds_total, st.rounds_accepted = 10, 10
    asyncio.run(_one_tick(app))
    high = _value("qkd_rounds_total", {"outcome": "accepted"})

    st.rounds_total, st.rounds_accepted = 1, 1      # restarted underneath us
    asyncio.run(_one_tick(app))
    assert _value("qkd_rounds_total", {"outcome": "accepted"}) >= high


def test_the_histogram_does_not_resample_an_idle_loop():
    """One observation per NEW round, not one per tick.

    Only the most recent duration is available here, so an unguarded observe()
    would pile up identical samples and skew every quantile toward whatever
    the last round happened to cost.
    """
    app = _app()
    st = app.state.pool.st
    st.rounds_total, st.rounds_accepted, st.last_round_ms = 1, 1, 100.0
    asyncio.run(_one_tick(app))
    after = _value("qkd_round_ms_count")
    asyncio.run(_one_tick(app))
    assert _value("qkd_round_ms_count") == after


# --------------------------------------------------------------------------
# The declaration and the producer must not drift apart again.
# --------------------------------------------------------------------------

def test_every_declared_metric_is_written_somewhere():
    """The check that would have caught this.

    A metric declared and never touched is a HELP string with no producer.
    """
    src = (ROOT / "services" / "bb84-kme" / "app" / "main.py").read_text(
        encoding="utf-8")
    import re
    declared = re.findall(r"^(M_[A-Z_]+) = (?:Counter|Gauge|Histogram)\(", src, re.M)
    assert declared, "no metrics found; this guard would pass vacuously"

    unwritten = []
    for name in declared:
        writes = re.findall(rf"{name}\.(?:labels\([^)]*\)\.)?(?:inc|set|observe)\(", src)
        if not writes:
            unwritten.append(name)
    assert not unwritten, (
        f"these metrics are declared and never written: {unwritten}. Either "
        f"produce them or delete the declaration -- /metrics publishing a "
        f"structural zero under a descriptive HELP string is worse than not "
        f"publishing it.")


def test_the_comment_that_described_absent_work_is_not_asserted_again():
    """The old comment may be QUOTED, but not restated as current.

    Quoting it in order to retract it is the record of why the code changed
    and must survive. A bare substring search flags the retraction itself --
    which is what happened when this test was first written, and is the same
    self-reference that `test_claims_about_the_pinned_strongswan_hold.py`
    solves with a window. Same technique here.
    """
    src = (ROOT / "services" / "bb84-kme" / "app" / "main.py").read_text(
        encoding="utf-8")
    lines = src.splitlines()
    needle = "we observe deltas via attribute snapshots"
    offenders = []
    for n, line in enumerate(lines):
        if needle not in line:
            continue
        window = "\n".join(lines[max(0, n - 6):n + 7]).lower()
        if any(w in window for w in ("used to sit here", "described work no line",
                                     "previous", "used to say", "was false")):
            continue
        offenders.append(n + 1)
    assert not offenders, (
        f"line(s) {offenders} state the old comment as current rather than "
        f"retracting it; it describes work no line performs")
