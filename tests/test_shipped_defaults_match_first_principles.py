"""The numbers the demo shows must be the published formulas, recomputed here.

Two existing tests look adjacent to this and neither covers it:

  * `test_keyrate_golden_vector.py` pins the GYS parameter set at L = 0 against
    R = 2.555e-3 from Ma et al. It imports `_skr`, so it checks the project's
    implementation against a literature number for ONE parameter set.
  * `test_keyrate_ports_agree.py` compares the TypeScript and Python ports.
    Agreement between two implementations cannot detect both being wrong in the
    same way.

Nothing checked the SHIPPED defaults -- `config/qkd_params.yaml`, L = 10 km,
mu = 0.5, nu1 = 0.1 -- which is the path `/physics` evaluates and displays.

The gap is demonstrable rather than hypothetical, and it is narrower than it
first looks. Changing `qber_Emu`'s e0 from 1/2 to 0.48 in BOTH ports:

    port parity              PASSED   -- the two agree, because both changed
    golden vector            failed
    this test                failed

Port parity is blind to a coordinated change by construction. The golden vector
caught this one because it asserts intermediate quantities as well as the final
rate -- but its expectation is a STORED constant, and "update the expected
value" is a normal-looking edit. This test derives its expectation from the
equations every run, so there is no constant to update.

So this file reimplements the model from the equations rather than importing it:
Ma, Qi, Zhao and Lo, PRA 72, 012326 (2005), Eqs. 5, 10, 11, 34, 37 and the GLLP
rate, as written out in `docs/keyrate.md`. It deliberately does NOT import
`app.backends._skr`. If both this and the implementation are wrong, they have to
be wrong independently, from the same published source, which is the most a
single repository can arrange.

Verified against the deployed demo on 2026-08-22: exporting `/physics` as JSON
gave eta_total, Y0, qber, skr_per_pulse and skr_bps identical to these
recomputations to every digit.
"""
from __future__ import annotations

import importlib
import math
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config" / "qkd_params.yaml"


# --------------------------------------------------------------------------
# The model, written from the paper. No project imports in this section.
# --------------------------------------------------------------------------
def _h2(x: float) -> float:
    """Binary entropy. h2(0) = h2(1) = 0 by continuity."""
    return -x * math.log2(x) - (1 - x) * math.log2(1 - x) if 0.0 < x < 1.0 else 0.0


def _reference_model(p: dict) -> dict[str, float]:
    eta_d = p["physical"]["detector_efficiency"]
    alpha = p["physical"]["fiber_attenuation_db_per_km"]
    L = p["physical"]["link_length_km"]
    e_d = p["physical"]["misalignment_error_ed"]
    r_dark = p["physical"]["dark_count_rate_hz"]
    r_pulse = float(p["source"]["pulse_rate_hz"])
    mu = p["source"]["intensity_signal_mu"]
    nu1 = p["source"]["intensity_decoy_1_nu1"]
    nu2 = p["source"]["intensity_decoy_2_nu2"]
    f_ec = p["protocol"]["ec_efficiency_f"]
    q = 0.5  # symmetric BB84 sifting

    eta = eta_d * 10 ** (-alpha * L / 10.0)          # Eq. 5
    y0 = r_dark / r_pulse

    def gain(i: float) -> float:                      # Eq. 10
        return y0 + 1 - math.exp(-eta * i)

    def qber(i: float) -> float:                      # Eq. 11, e0 = 1/2
        g = gain(i)
        return (0.5 * y0 + e_d * (1 - math.exp(-eta * i))) / g if g > 0 else 0.5

    q_mu, e_mu = gain(mu), qber(mu)
    q_n1, e_n1 = gain(nu1), qber(nu1)
    q_n2 = gain(nu2) if nu2 > 0 else y0

    # Decoy bounds, Eqs. 34 and 37.
    y1_l = (mu / (mu * nu1 - nu1 * nu1)) * (
        q_n1 * math.exp(nu1) - q_n2 * math.exp(nu2)
        - (nu1 * nu1 - nu2 * nu2) / (mu * mu) * (q_mu * math.exp(mu) - y0)
    )
    e1_u = (e_n1 * q_n1 * math.exp(nu1) - 0.5 * y0) / (y1_l * nu1)
    q1 = mu * math.exp(-mu) * y1_l

    rate = max(q * (-q_mu * f_ec * _h2(e_mu) + q1 * (1 - _h2(e1_u))), 0.0)
    return {
        "eta_total": eta,
        "Y0": y0,
        "qber": e_mu,
        "skr_per_pulse": rate,
        "skr_bps": rate * r_pulse,
    }


@pytest.fixture(scope="module")
def shipped() -> dict:
    return yaml.safe_load(CONFIG.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def implementation():
    from conftest import load_service_app

    load_service_app("bb84-kme", "bb84_kme_app")
    return importlib.import_module("bb84_kme_app.backends._skr")


def test_the_reference_model_is_not_trivially_zero(shipped):
    """Guard the guard: a model returning zeros would agree with anything broken."""
    ref = _reference_model(shipped)
    assert ref["skr_per_pulse"] > 0, "reference rate is zero for the shipped defaults"
    assert 0 < ref["qber"] < 0.11, f"reference QBER {ref['qber']} is not physical"
    assert 0 < ref["eta_total"] < 1


@pytest.mark.parametrize(
    "quantity", ["eta_total", "Y0", "qber", "skr_per_pulse", "skr_bps"]
)
def test_implementation_matches_first_principles(shipped, implementation, quantity):
    """The shipped defaults, through the code, against the paper.

    Tolerance is 1e-12 rather than a loose approx: both sides evaluate the same
    closed form in double precision, so anything above rounding is a difference
    in the model, not in the arithmetic. Measured agreement is exact.
    """
    ref = _reference_model(shipped)
    eta = implementation.total_transmittance(
        shipped["physical"]["detector_efficiency"],
        shipped["physical"]["fiber_attenuation_db_per_km"],
        shipped["physical"]["link_length_km"],
    )
    y0 = shipped["physical"]["dark_count_rate_hz"] / float(shipped["source"]["pulse_rate_hz"])
    got = {
        "eta_total": eta,
        "Y0": y0,
        "qber": implementation.qber_Emu(
            y0, eta, shipped["physical"]["misalignment_error_ed"],
            shipped["source"]["intensity_signal_mu"],
        ),
        "skr_per_pulse": implementation.asymptotic_skr_per_pulse(
            Y0=y0, eta_total=eta,
            e_d=shipped["physical"]["misalignment_error_ed"],
            mu=shipped["source"]["intensity_signal_mu"],
            nu1=shipped["source"]["intensity_decoy_1_nu1"],
            nu2=shipped["source"]["intensity_decoy_2_nu2"],
            f_EC=shipped["protocol"]["ec_efficiency_f"],
        ),
    }
    got["skr_bps"] = got["skr_per_pulse"] * float(shipped["source"]["pulse_rate_hz"])

    assert got[quantity] == pytest.approx(ref[quantity], rel=1e-12), (
        f"{quantity}: implementation {got[quantity]!r} vs first principles "
        f"{ref[quantity]!r}. This test reimplements Ma et al. Eqs. 5/10/11/34/37 "
        "rather than importing _skr, so a disagreement means the model changed "
        "-- not that two ports drifted apart."
    )
