"""TNO's asymptotic decoy-state rates on the shipped configuration are pinned.

tno-qkd-key-rate v2.0.5 (2026-11-18) corrected TNO's *finite-key* estimator.
The `tno` backend and the cross-check on /verify use only the asymptotic
estimators, so on 2026-11-25 `compute_tno_rate` was run under v2.0.4 and under
v2.0.5 in the bb84-kme image at 13 distances from 0 to 300 km: the rates and the
optimal intensities were identical to the last digit. This pins four of those
rates, so the next bump of the submodule -- or of NumPy or SciPy underneath it,
which the image does not pin -- says whether the numbers the page shows moved,
instead of that being found by reading TNO's changelog.

It runs where TNO is installed: inside the bb84-kme image, in CI's step
"Backend physics inside the image that has SimQN and SeQUeNCe", which fails on
any skip. Outside the image it skips.

If it fails, read which test failed first. A changed configuration value means
the numbers below have to be recomputed, not that TNO changed. A moved rate with
an unchanged configuration is the finding: record what moved it.

Tolerances: 1e-4 relative on the rate and 5e-3 absolute on the intensity. The
optimum is flat in the intensity, so an optimiser that stops a little elsewhere
moves the intensity far more than the rate; a change of the kind v2.0.5 made to
the finite-key rates (10-15 %) is three orders of magnitude outside both.
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

#: link length (km) -> (rate per pulse, optimal mu), from `compute_tno_rate`.
#: Computed 2026-11-25 in the bb84-kme image: Python 3.12.13, NumPy 2.5.3,
#: SciPy 1.18.1, tno-qkd-key-rate v2.0.4 and v2.0.5 (the same to the last digit).
RATES = {
    10.0: (0.04571317747870629, 0.946638867196751),
    50.0: (0.0071273653427372345, 0.944085752750927),
    100.0: (0.0006212221189419873, 0.9444684104103023),
    150.0: (1.1199908508336723e-05, 0.615938691827998),
}


def _rate(km: float) -> dict:
    from app.backends.base import cfg_from_yaml
    from app.backends.tno_backend import compute_tno_rate

    cfg = copy.copy(cfg_from_yaml())
    cfg.link_length_km = km
    return compute_tno_rate(cfg)


def test_the_configuration_is_the_one_the_numbers_came_from():
    from app import config_loader as cl

    changed = {k: (v, cl.require(k)) for k, v in CONFIG.items() if float(cl.require(k)) != v}
    assert not changed, (
        "config/qkd_params.yaml changed since the rates in this file were computed; "
        f"recompute RATES with the new values (pinned, now): {changed}")


@pytest.mark.parametrize("km", sorted(RATES))
def test_the_asymptotic_rate_has_not_moved(km):
    want_rate, want_mu = RATES[km]
    got = _rate(km)
    assert got["protocol"] == "BB84 decoy (asymptotic)", got
    assert got["rate_per_pulse"] == pytest.approx(want_rate, rel=1e-4), (
        f"{km} km: TNO's asymptotic decoy rate moved from {want_rate!r} to {got['rate_per_pulse']!r}")
    assert got["mu_opt"] == pytest.approx(want_mu, abs=5e-3), (
        f"{km} km: the optimal intensity moved from {want_mu!r} to {got['mu_opt']!r}")


def test_far_out_there_is_still_no_key():
    got = _rate(300.0)
    assert got["rate_per_pulse"] == 0.0, got
    assert got["skr_bps"] == 0.0, got
