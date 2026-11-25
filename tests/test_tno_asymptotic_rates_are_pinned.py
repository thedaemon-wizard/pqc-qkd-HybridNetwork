"""TNO's asymptotic decoy-state rates on the shipped configuration are pinned.

tno-qkd-key-rate v2.0.5 (2026-11-18) corrected TNO's *finite-key* estimator.
The `tno` backend and the cross-check on /verify use only the asymptotic
estimators, so on 2026-11-25 `compute_tno_rate` was run under v2.0.4 and under
v2.0.5 in the bb84-kme image at 13 distances from 0 to 300 km: on one machine,
the rates and the optimal intensities were identical to the last digit. This
pins what a later bump of the submodule -- or of NumPy or SciPy underneath it,
which the image does not pin -- could move, instead of that being found by
reading TNO's changelog.

Two things are pinned, because they are reproducible to very different degrees:

  * TNO's rate at fixed intensities (`compute_rate`): the decoy bounds, a
    linear program, and the key-rate formula. On two machines with different
    vector units it agreed to 4e-10 relative (2026-11-25), so it is held to
    1e-6. A change to TNO's model shows up here first.
  * The optimum `compute_tno_rate` reports. TNO finds it with `trust-constr`
    over finite differences of that linear program, and the optimum is flat
    in the decoy intensities; where it stops depends on the CPU, and CI
    runners follow one machine or the other (the version of this test that
    held the optimum to 1e-4 passed in PR #160's run and failed on `main`).
    With the drift passed as an angle (below), the two machines' optima were
    0.02 % apart at 10 km, 0.05 % at 50 km, 0.9 % at 100 km and 8.9 % at
    150 km. So the optimum is held to 1 % at 10 and 50 km, 5 % at 100 km and
    30 % at 150 km, its signal intensity to 0.05, and it must not fall below
    the rate at the fixed intensities, a point any working optimiser beats.
    The verdict on /verify tests the ratio against [0.1, 10], far wider.

And one thing about what TNO is given: `polarization_drift` is an angle, and
the error it adds is its sine squared. `_build_detector` passed e_d itself until
2026-11-25, so TNO's error rate at 10 km was 0.04 % where the configuration
says 1.5 %; `test_tno_sees_the_misalignment_the_configuration_states` holds the
mapping, and every number below was recomputed with it.

It runs where TNO is installed: inside the bb84-kme image, in CI's step
"Backend physics inside the image that has SimQN and SeQUeNCe", which fails on
any skip. Outside the image it skips.

If it fails, read which test failed first. A changed configuration value means
the numbers below have to be recomputed, not that TNO changed. A moved rate at
fixed intensities with an unchanged configuration is the finding: record what
moved it.
"""
from __future__ import annotations

import copy
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "bb84-kme"))
os.environ.setdefault("QKD_PARAMS_FILE", str(ROOT / "config" / "qkd_params.yaml"))

pytest.importorskip("tno.quantum.communication.qkd_key_rate")

#: The values of config/qkd_params.yaml that the numbers below were computed with.
CONFIG = {
    "physical.fiber_attenuation_db_per_km": 0.2,
    "physical.detector_efficiency": 0.2,
    "physical.dark_count_rate_hz": 100.0,
    "physical.misalignment_error_ed": 0.015,
    "detector.efficiency_system": 1.0,
    "detector.jitter_source_s": 0.0,
    "detector.jitter_detector_s": 5e-11,
    "detector.dead_time_s": 4.5e-08,
    "detector.detection_frequency_hz": 1.0e7,
    "detector.detection_window": 5,
}

#: link length (km) -> (intensities: signal, decoy, decoy; TNO's rate per pulse at them).
#: Computed 2026-11-25 in the bb84-kme image (Python 3.12.13, NumPy 2.5.3, SciPy 1.18.1,
#: tno-qkd-key-rate v2.0.5), with the drift passed as an angle; a second machine agreed
#: to 2e-9 relative.
AT_FIXED = {
    10.0: ([0.9, 0.1, 0.01], 0.025673707996832516),
    50.0: ([0.9, 0.1, 0.01], 0.00385820921314073),
    100.0: ([0.9, 0.1, 0.01], 0.0003248509679873259),
    150.0: ([0.45, 0.05, 0.005], 1.4484154955986172e-06),
}

#: link length (km) -> (the optimum's rate per pulse, its signal intensity, the relative
#: spread allowed on the rate), from `compute_tno_rate` on the same day and image.
OPTIMUM = {
    10.0: (0.02946496465458687, 0.7544460156185032, 0.01),
    50.0: (0.0045509546128638684, 0.7372672941262531, 0.01),
    100.0: (0.0003985702574223266, 0.7189483836760616, 0.05),
    150.0: (2.5795538231308866e-06, 0.43433653417629947, 0.30),
}


def _cfg(km: float):
    from app.backends.base import cfg_from_yaml

    cfg = copy.copy(cfg_from_yaml())
    cfg.link_length_km = km
    return cfg


def test_tno_sees_the_misalignment_the_configuration_states():
    """The drift is the angle whose sine squared is e_d, and TNO's error rate near zero length is e_d."""
    import math

    from app.backends.tno_backend import _build_detector
    from tno.quantum.communication.qkd_key_rate.quantum import _detector
    from tno.quantum.communication.qkd_key_rate.quantum.bb84 import compute_gain_and_error_rate

    cfg = _cfg(1.0)
    e_d = float(cfg.misalignment_error_ed)
    det = _build_detector(cfg)
    assert det.polarization_drift == pytest.approx(math.asin(math.sqrt(e_d)), rel=1e-12)
    assert det.error_detector == 0.0
    if e_d == 0.015:  # TNO's own default drift is this configuration's e_d, as an angle
        assert det.polarization_drift == pytest.approx(float(_detector.DEFAULT_POLARIZATION_DRIFT), rel=1e-12)
    _, error = compute_gain_and_error_rate(det, [0.5], float(cfg.fiber_attenuation_db_per_km) * 1.0)
    # e_d plus the dark counts' share, which at 1 km is about 1e-4 of it.
    assert float(error[0]) == pytest.approx(e_d, abs=1e-3), (
        f"TNO's error rate at 1 km is {float(error[0])!r}, the configuration's misalignment {e_d}")


def test_the_configuration_is_the_one_the_numbers_came_from():
    from app import config_loader as cl

    changed = {k: (v, cl.require(k)) for k, v in CONFIG.items() if float(cl.require(k)) != v}
    assert not changed, (
        "config/qkd_params.yaml changed since the rates in this file were computed; "
        f"recompute AT_FIXED and OPTIMUM with the new values (pinned, now): {changed}")


@pytest.mark.parametrize("km", sorted(AT_FIXED))
def test_tnos_rate_at_fixed_intensities_has_not_moved(km):
    from app.backends.tno_backend import _build_detector
    from tno.quantum.communication.qkd_key_rate.quantum.bb84 import BB84AsymptoticKeyRateEstimate

    mu, want = AT_FIXED[km]
    cfg = _cfg(km)
    est = BB84AsymptoticKeyRateEstimate(detector=_build_detector(cfg), number_of_decoy=2)
    got = est.compute_rate(mu=mu, attenuation=float(cfg.fiber_attenuation_db_per_km) * km)
    assert got == pytest.approx(want, rel=1e-6), (
        f"{km} km: TNO's asymptotic decoy rate at intensities {mu} moved from {want!r} to {got!r}")


@pytest.mark.parametrize("km", sorted(OPTIMUM))
def test_the_optimum_is_where_it_was_within_the_spread_between_cpus(km):
    from app.backends.tno_backend import compute_tno_rate

    want_rate, want_mu, spread = OPTIMUM[km]
    got = compute_tno_rate(_cfg(km))
    assert got["protocol"] == "BB84 decoy (asymptotic)", got
    assert got["rate_per_pulse"] == pytest.approx(want_rate, rel=spread), (
        f"{km} km: TNO's optimum moved from {want_rate!r} to {got['rate_per_pulse']!r}, "
        f"more than the {spread:.0%} that CPUs spread it by")
    assert got["rate_per_pulse"] >= AT_FIXED[km][1], (
        f"{km} km: the optimiser returned {got['rate_per_pulse']!r}, less than the rate "
        f"{AT_FIXED[km][1]!r} at the fixed intensities {AT_FIXED[km][0]}")
    assert got["mu_opt"] == pytest.approx(want_mu, abs=0.05), (
        f"{km} km: the optimal signal intensity moved from {want_mu!r} to {got['mu_opt']!r}")


def test_far_out_there_is_still_no_key():
    from app.backends.tno_backend import compute_tno_rate

    got = compute_tno_rate(_cfg(300.0))
    assert got["rate_per_pulse"] == 0.0, got
    assert got["skr_bps"] == 0.0, got
