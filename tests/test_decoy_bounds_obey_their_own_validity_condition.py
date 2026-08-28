"""The two-decoy bound must refuse inputs its theorem does not cover.

Ma, Qi, Zhao, Lo, PRA 72, 012326 (2005), arXiv:quant-ph/0503005, Eq. (13)
states the validity condition for the Eq. (18) lower bound on Y1::

    0 <= nu2 < nu1     and     nu1 + nu2 < mu

`_skr.py` tested `denom <= 0` instead. That is not equivalent. The denominator

    mu*nu1 - mu*nu2 - nu1^2 + nu2^2  ==  (nu1 - nu2) * (mu - nu1 - nu2)

is a product of the two Eq. (13) margins, so it is positive when BOTH are
negative -- when both halves of the condition are violated at once. Measured
before the fix, with the shipped mu and nu1 and a nu2 typed into the editable
field on /physics::

    mu=0.5  nu1=0.1  nu2=0.45   denom=+0.01750   Eq.(13) satisfied: False
      returned 1.4912e-02  against a legitimate 1.2334e-02   (+21 %)

A 21 % overestimate, displayed as a secret-key rate, with no theorem behind it,
reachable from the public demo in one form field.

The second defect here is the mirror of one already fixed. Y1's denominator had
been corrected to the general two-decoy form, but e1 still used Eq. (33) -- the
Vacuum+Weak form, which substitutes nu2 = 0. So the two halves of the same rate
assumed different nu2. It errs optimistic, and the optimiser grid in
config/qkd_params.yaml searches nu2 = 0.01, so it was live.
"""
from __future__ import annotations

import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "services" / "bb84-kme"))

from app.backends._skr import (  # noqa: E402
    asymptotic_skr_per_pulse,
    total_transmittance,
)

Y0 = 1.0e-7
ETA = total_transmittance(0.2, 0.2, 10.0)
BASE = dict(Y0=Y0, eta_total=ETA, e_d=0.015, f_EC=1.16)


def rate(mu: float, nu1: float, nu2: float) -> float:
    return asymptotic_skr_per_pulse(mu=mu, nu1=nu1, nu2=nu2, **BASE)


def eq13(mu: float, nu1: float, nu2: float) -> bool:
    return 0.0 <= nu2 < nu1 and nu1 + nu2 < mu


# --------------------------------------------------------------------------
# Eq. (13) is enforced, including the case the old guard let through.
# --------------------------------------------------------------------------

@pytest.mark.parametrize("mu,nu1,nu2,why", [
    (0.5, 0.1, 0.45, "BOTH margins negative -- denom is positive, old guard passed"),
    (0.5, 0.1, 0.2, "nu2 > nu1"),
    (0.5, 0.4, 0.3, "nu1 + nu2 > mu"),
    (0.5, 0.1, -0.01, "nu2 < 0"),
    (0.5, 0.1, 0.1, "nu2 == nu1, so nu1 - nu2 == 0"),
    (0.5, 0.5, 0.0, "nu1 == mu"),
])
def test_an_input_outside_eq_13_yields_no_rate(mu, nu1, nu2, why):
    assert not eq13(mu, nu1, nu2), f"test premise wrong: {why}"
    assert rate(mu, nu1, nu2) == 0.0, (
        f"mu={mu} nu1={nu1} nu2={nu2} ({why}) produced a rate the Eq. (18) "
        f"bound does not cover")


def test_the_specific_21_percent_overestimate_is_gone():
    """The exact triple measured before the fix."""
    bad = rate(0.5, 0.1, 0.45)
    good = rate(0.5, 0.1, 0.0)
    assert bad == 0.0, f"still returns {bad:.4e}"
    # Pin the legitimate value so this test cannot pass by the rate collapsing
    # everywhere.
    assert good == pytest.approx(1.2334e-02, rel=1e-3)


def test_the_old_guard_would_have_let_it_through():
    """Not vacuous: show `denom > 0` really does hold for the illegal input."""
    mu, nu1, nu2 = 0.5, 0.1, 0.45
    denom = mu * nu1 - mu * nu2 - nu1 * nu1 + nu2 * nu2
    assert denom > 0, "premise: the old `denom <= 0` test passes here"
    assert not eq13(mu, nu1, nu2), "premise: yet Eq. (13) is violated"


def test_denominator_factorises_into_the_two_eq_13_margins():
    """Why `denom > 0` cannot stand in for Eq. (13): it is their product."""
    for mu, nu1, nu2 in [(0.5, 0.1, 0.0), (0.5, 0.1, 0.45), (0.7, 0.2, 0.1)]:
        denom = mu * nu1 - mu * nu2 - nu1 * nu1 + nu2 * nu2
        assert denom == pytest.approx((nu1 - nu2) * (mu - nu1 - nu2))


# --------------------------------------------------------------------------
# Legal inputs still work, and the shipped one is untouched.
# --------------------------------------------------------------------------

@pytest.mark.parametrize("mu,nu1,nu2", [
    (0.5, 0.1, 0.0), (0.5, 0.1, 0.01), (0.5, 0.1, 0.05),
    (0.5, 0.2, 0.05), (0.6, 0.15, 0.02),
])
def test_a_legal_input_still_produces_a_rate(mu, nu1, nu2):
    assert eq13(mu, nu1, nu2), "test premise wrong"
    assert rate(mu, nu1, nu2) > 0.0


def test_the_shipped_configuration_is_bit_identical():
    """nu2 = 0 must be untouched, or the golden vector moves."""
    assert rate(0.5, 0.1, 0.0) == pytest.approx(1.233366e-02, rel=1e-6)


# --------------------------------------------------------------------------
# e1 uses the general Eq. (22), not the nu2 = 0 form.
# --------------------------------------------------------------------------

def test_e1_uses_nu2_so_the_rate_falls_as_nu2_rises():
    """The Vacuum+Weak e1 ignored nu2, so it read the same at every nu2.

    Eq. (22)'s numerator subtracts E_nu2 Q_nu2 e^nu2, which grows with nu2, so
    the bound on e1 loosens and the rate falls. A rate that does NOT move with
    nu2 is the signature of the old form.
    """
    rates = [rate(0.5, 0.1, n2) for n2 in (0.0, 0.01, 0.03, 0.05)]
    assert rates == sorted(rates, reverse=True), rates
    assert len(set(rates)) == len(rates), (
        "the rate is insensitive to nu2, which means e1 is still using the "
        "nu2 = 0 form while Y1 uses the general one")


def test_the_old_e1_form_was_optimistic_by_the_measured_amount():
    """Direction and rough size, so a regression is recognisable."""
    r0 = rate(0.5, 0.1, 0.0)
    r1 = rate(0.5, 0.1, 0.01)
    r5 = rate(0.5, 0.1, 0.05)
    # The old form returned a HIGHER rate at nu2 > 0 than the correct one.
    # Correct rates must now sit below the nu2 = 0 value.
    assert r1 < r0 and r5 < r1
    assert (r0 - r1) / r0 == pytest.approx(0.0064, abs=0.004)


def test_at_nu2_zero_both_e1_forms_agree_exactly():
    """Eq. (22) reduces to Eq. (33) as nu2 -> 0; the shipped path must not jump."""
    near = rate(0.5, 0.1, 1e-9)
    exact = rate(0.5, 0.1, 0.0)
    assert near == pytest.approx(exact, rel=1e-6), (
        f"discontinuity at nu2 = 0: {exact:.6e} vs {near:.6e}")
