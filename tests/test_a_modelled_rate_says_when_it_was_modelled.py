"""`modelled_skr_bps` must say WHICH configuration it was modelled from.

`skr_provenance` already says the figure is closed-form from config rather than
measured per round. That is honest about the KIND of number. It is silent about
the VINTAGE, and the vintage can be arbitrarily old.

The producer refreshes `modelled_skr_bps` only when a round completes
(`keypool.py` `_record`), and it only runs a round when the key buffer has
drained below the low watermark. An idle pool runs no rounds, so the field
keeps reporting a rate for a configuration the operator has already replaced.

Measured against the public demo 2026-08-28::

    baseline (10 km)                        3.9866e+06
    POST link_length_km = 100, +3 s         3.9866e+06   <-- still the 10 km rate
    ... 40 s later, after a round ran       0.0000e+00   <-- correct: 100 km is
                                                             past the 98.49 km
                                                             finite-key crossing

`/benchmarks` polls this every second and plots it, so for those 40 seconds it
drew a rate for a distance nobody had configured, with nothing in the payload
distinguishing that from a current reading.

This was first mis-diagnosed as "/api/stats ignores link_length_km". It does
not: the override propagates correctly through `config_loader`'s listener to
`backend.update_config`. The defect is that the derived value is only recomputed
on an event that may not happen for an unbounded time.
"""
from __future__ import annotations

import os
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "services" / "bb84-kme"))

# BEFORE importing config_loader. `CONFIG_PATH` is resolved at MODULE IMPORT
# time from this variable, defaulting to /etc/pqcqkd/qkd_params.yaml -- which
# does not exist outside the container. Importing config_loader without it
# fixes that dead path for the whole process, so every later test sees an empty
# config and `cfg_from_yaml()` fails with "float() argument must be ... not
# NoneType".
#
# This file sorts first alphabetically, so getting it wrong broke nine tests in
# two other files while this one passed. The convention is set by
# tests/test_skr_is_not_a_sifting_ratio.py:30; follow it.
os.environ.setdefault("QKD_PARAMS_FILE", str(REPO / "config" / "qkd_params.yaml"))

import pytest  # noqa: E402
from app import config_loader as cl  # noqa: E402
from app.keypool import PoolStats  # noqa: E402


@pytest.fixture(autouse=True)
def _restore_overrides():
    """config_loader holds PROCESS-WIDE state, so these tests must clean up.

    Without this the link_length_km overrides below leak into every test that
    runs afterwards in the same process -- nine of them failed that way on the
    first run of this file, all with rates for a distance no other test had
    set. A test that changes global state and does not restore it does not
    fail itself; it fails whatever runs next, which is far harder to trace.
    """
    yield
    cl.clear_overrides()


# --------------------------------------------------------------------------
# The generation counter.
# --------------------------------------------------------------------------

def test_an_override_bumps_the_generation():
    before = cl.generation()
    cl.set_overrides({"physical": {"link_length_km": 42.0}})
    assert cl.generation() == before + 1
    cl.set_overrides({"physical": {"link_length_km": 10.0}})
    assert cl.generation() == before + 2


def test_the_generation_never_goes_backwards():
    seen = [cl.generation()]
    for km in (11.0, 12.0, 13.0):
        cl.set_overrides({"physical": {"link_length_km": km}})
        seen.append(cl.generation())
    assert seen == sorted(seen), seen
    assert len(set(seen)) == len(seen), "an override did not bump the counter"


# --------------------------------------------------------------------------
# The staleness flag.
# --------------------------------------------------------------------------

def test_an_unset_generation_does_not_read_as_current():
    """-1 == -1 would say "current" before the first round has ever run."""
    s = PoolStats()
    assert s.skr_config_generation == -1
    assert s.skr_reflects_current_config is False


def test_the_flag_is_a_bool_not_two_integers_for_the_reader_to_compare():
    """/benchmarks polls this every second; it should not need the convention."""
    names = set(PoolStats.__dataclass_fields__)
    assert "skr_reflects_current_config" in names
    assert "skr_config_generation" in names, "keep the raw values for diagnosis"
    assert "config_generation" in names
    assert PoolStats.__dataclass_fields__[
        "skr_reflects_current_config"].type in ("bool", bool)


def test_the_provenance_string_still_says_it_is_modelled():
    """The new field ADDS vintage; it must not replace the kind."""
    s = PoolStats()
    assert "not measured per round" in s.skr_provenance


# --------------------------------------------------------------------------
# The producer records the generation it computed at.
# --------------------------------------------------------------------------

def test_the_record_path_stamps_the_generation():
    src = (REPO / "services" / "bb84-kme" / "app" / "keypool.py").read_text(
        encoding="utf-8")
    record = src[src.index("async def _record"):]
    record = record[:record.index("\n    async def ")] if "\n    async def " in record \
        else record[:3000]
    assert "self._stats.modelled_skr_bps = r.skr_bps" in record
    assert "skr_config_generation = cl.generation()" in record, (
        "the rate is refreshed without stamping the generation it came from, "
        "so a stale value is again indistinguishable from a current one")


def test_the_two_assignments_are_adjacent():
    """They must not drift apart into separate branches.

    If the rate is ever updated on a path that does not stamp the generation,
    the flag silently starts lying in the safe-looking direction (claiming
    current when it is not).
    """
    src = (REPO / "services" / "bb84-kme" / "app" / "keypool.py").read_text(
        encoding="utf-8")
    lines = src.splitlines()
    rate = [i for i, l in enumerate(lines)
            if "self._stats.modelled_skr_bps = " in l]
    stamp = [i for i, l in enumerate(lines)
             if "skr_config_generation = cl.generation()" in l]
    assert len(rate) == 1 and len(stamp) == 1, (rate, stamp)
    assert stamp[0] - rate[0] == 1, (
        f"the generation stamp is {stamp[0] - rate[0]} lines from the rate "
        f"assignment; keep them adjacent so neither can be added without the "
        f"other")


def test_clearing_overrides_also_bumps_the_generation():
    """A reset changes the effective parameters as much as an override does.

    Without this, a rate computed while an override was in force would keep
    reading "current" after the reset -- stale in the direction that looks
    safe.
    """
    cl.set_overrides({"physical": {"link_length_km": 77.0}})
    after_set = cl.generation()
    cl.clear_overrides()
    assert cl.generation() == after_set + 1


def test_a_reload_bumps_it_too():
    """Asserted on the source, NOT by calling reload().

    `cl.reload()` re-reads the YAML through a path that does not resolve in the
    pytest process, so it replaces the process-wide cache with an empty dict
    and every later test sees `cfg_from_yaml()` fail with
    "float() argument must be ... not NoneType". Calling it here broke nine
    tests in other files while this one passed.

    The behaviour still needs pinning -- a reload changes the effective
    parameters, so anything derived before it is stale -- but not at the price
    of a landmine for whatever runs next.
    """
    src = (REPO / "services" / "bb84-kme" / "app" / "config_loader.py").read_text(
        encoding="utf-8")
    body = src[src.index("def reload("):src.index("def params(")]
    assert "_cache.generation += 1" in body, (
        "reload() no longer bumps the generation, so a value derived before a "
        "file reload would still report as current")
