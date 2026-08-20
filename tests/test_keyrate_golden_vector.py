"""Golden-vector tests for the decoy-state BB84 key-rate model.

The same closed-form model is implemented THREE times in this repository:

    services/bb84-kme/app/backends/_skr.py        (the backends' reference)
    services/webui-frontend/src/lib/sim/keyrate.ts (the client-side port)
    tools/precompute_keyrate_table_fallback.py    (the offline table builder)

Nothing previously pinned any of them to a published number, so all three could
drift together and stay "consistent" while being wrong.

The vector below is the standard GYS parameter set worked through Ma, Qi, Zhao
and Lo, *Practical decoy state for quantum key distribution*, Phys. Rev. A 72,
012326 (2005) -- equations 5, 10, 11 and the GLLP rate. Values are quoted to
the precision the derivation gives.
"""

from __future__ import annotations

import importlib
import math

import pytest
from conftest import load_service_app

load_service_app("bb84-kme", "bb84_kme_app")
_skr = importlib.import_module("bb84_kme_app.backends._skr")

# --- GYS parameter set, at zero fibre length -------------------------------
# eta is the total transmittance: at L = 0 the fibre term 10^(-alpha*L/10) is
# unity, so eta = eta_Bob = 0.045.
ETA = 0.045
Y0 = 1.7e-6          # dark-count yield
E_D = 0.033          # detector misalignment
MU = 0.48            # signal intensity
F_EC = 1.22          # error-correction efficiency
Q_SIFT = 0.5         # basis-reconciliation factor for symmetric BB84

# Expected values (Ma et al. 2005, GYS worked example).
EXP_Q_MU = 2.13701e-2
EXP_E_MU = 3.3037e-2
EXP_Q1 = 1.33670e-2
EXP_E1 = 3.3017e-2
EXP_RATE = 2.555e-3

REL_TOL = 1e-4


def test_transmittance_is_unity_at_zero_length():
    assert _skr.total_transmittance(ETA, 0.20, 0.0) == pytest.approx(ETA, rel=1e-12)


def test_transmittance_matches_fibre_attenuation_law():
    """eta = eta_d * 10^(-alpha L / 10); 0.2 dB/km over 50 km is 10 dB of loss."""
    got = _skr.total_transmittance(1.0, 0.20, 50.0)
    assert got == pytest.approx(0.1, rel=1e-12)


def test_gain_matches_published_value():
    """Q_mu = Y0 + 1 - exp(-eta mu)   (Ma et al. eq. 10)."""
    got = _skr.gain_Qmu(Y0, ETA, MU)
    assert got == pytest.approx(EXP_Q_MU, rel=REL_TOL), (
        f"Q_mu = {got:.6e}, published {EXP_Q_MU:.6e}"
    )


def test_qber_matches_published_value():
    """E_mu = [e_0 Y0 + e_d (1 - exp(-eta mu))] / Q_mu, with e_0 = 1/2 (eq. 11)."""
    got = _skr.qber_Emu(Y0, ETA, E_D, MU)
    assert got == pytest.approx(EXP_E_MU, rel=REL_TOL), (
        f"E_mu = {got:.6e}, published {EXP_E_MU:.6e}"
    )


def test_binary_entropy_reference_points():
    # H2(x) = -x log2 x - (1-x) log2 (1-x)
    assert _skr.H2(0.5) == pytest.approx(1.0, rel=1e-12)
    # At the classic ~11 % BB84 threshold, H2 = 0.4999159...
    #   0.11 * 3.184425 + 0.89 * 0.168123 = 0.499916
    assert _skr.H2(0.11) == pytest.approx(0.4999160, rel=1e-6)
    assert _skr.H2(0.01) == pytest.approx(0.0807931, rel=1e-6)
    # Symmetric about 1/2.
    assert _skr.H2(0.3) == pytest.approx(_skr.H2(0.7), rel=1e-12)
    # Outside (0,1) the entropy is defined as 0 rather than raising.
    assert _skr.H2(0.0) == 0.0
    assert _skr.H2(1.0) == 0.0


def test_gllp_rate_reproduces_published_value():
    """The asymptotic GLLP rate, with perfect (infinite) decoy estimation.

    With infinitely many decoy states the single-photon yield and error rate
    are known exactly:
        Y1 = Y0 + eta,   e1 = (e_0 Y0 + e_d eta) / Y1,   Q1 = Y1 mu exp(-mu)
    so this exercises the rate expression itself, independently of the
    two-decoy bound tested below.
    """
    Q_mu = _skr.gain_Qmu(Y0, ETA, MU)
    E_mu = _skr.qber_Emu(Y0, ETA, E_D, MU)

    Y1 = Y0 + ETA
    e1 = (0.5 * Y0 + E_D * ETA) / Y1
    Q1 = Y1 * MU * math.exp(-MU)

    assert Q1 == pytest.approx(EXP_Q1, rel=REL_TOL), f"Q1 = {Q1:.6e}"
    assert e1 == pytest.approx(EXP_E1, rel=REL_TOL), f"e1 = {e1:.6e}"

    rate = Q_SIFT * (-Q_mu * F_EC * _skr.H2(E_mu) + Q1 * (1.0 - _skr.H2(e1)))
    assert rate == pytest.approx(EXP_RATE, rel=1e-3), (
        f"R = {rate:.6e} bits/pulse, published {EXP_RATE:.6e}. "
        "A mismatch here is in the asymptotic core, not the decoy estimator."
    )


def test_two_decoy_bound_is_below_infinite_decoy_rate():
    """The two-decoy estimate is a LOWER bound, so it must not exceed the ideal.

    A two-decoy result above the infinite-decoy rate would mean the bound is
    unsound -- exactly the kind of sign or algebra error this guards.
    """
    Q_mu = _skr.gain_Qmu(Y0, ETA, MU)
    E_mu = _skr.qber_Emu(Y0, ETA, E_D, MU)
    Y1 = Y0 + ETA
    e1 = (0.5 * Y0 + E_D * ETA) / Y1
    ideal = Q_SIFT * (
        -Q_mu * F_EC * _skr.H2(E_mu) + Y1 * MU * math.exp(-MU) * (1.0 - _skr.H2(e1))
    )

    two_decoy = _skr.asymptotic_skr_per_pulse(
        Y0=Y0, eta_total=ETA, e_d=E_D, mu=MU, nu1=0.05, nu2=0.0, f_EC=F_EC,
    )

    assert 0.0 < two_decoy <= ideal, (
        f"two-decoy {two_decoy:.6e} must lie in (0, {ideal:.6e}]"
    )


def test_rate_decreases_with_distance():
    """Monotonicity: more fibre, less key. Guards against a sign error in eta."""
    rates = [
        _skr.asymptotic_skr_per_pulse(
            Y0=Y0,
            eta_total=_skr.total_transmittance(0.2, 0.20, L),
            e_d=E_D, mu=MU, nu1=0.05, nu2=0.0, f_EC=F_EC,
        )
        for L in (0.0, 25.0, 50.0, 100.0)
    ]
    assert rates == sorted(rates, reverse=True), rates


def test_rate_is_zero_when_qber_exceeds_the_bound():
    """Above ~11 % QBER no secret key may be produced."""
    rate = _skr.asymptotic_skr_per_pulse(
        Y0=Y0, eta_total=ETA, e_d=0.20, mu=MU, nu1=0.05, nu2=0.0, f_EC=F_EC,
    )
    assert rate == 0.0


def test_finite_key_penalty_shrinks_with_block_size():
    """The correction goes as sqrt(2/N), so it must fall as N grows."""
    eps = 1e-10
    p_small = _skr.finite_key_penalty(10**6, eps)
    p_large = _skr.finite_key_penalty(10**9, eps)
    assert p_small > p_large > 0.0
    assert p_small / p_large == pytest.approx(math.sqrt(1000.0), rel=1e-6)
