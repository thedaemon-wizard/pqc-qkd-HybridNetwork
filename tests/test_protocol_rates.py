"""The key-rate curves on /qkd-protocols, held to their sources.

tools/protocol_rates.py is the reference; protocolRates.test.ts holds the browser
port to the golden file it writes. Here the reference itself is checked three ways
that do not use its own closed forms:

  * the single-photon yield and error rate, Ma and Razavi Eqs. (A9) and (A11), by
    exact two-photon linear optics with threshold detectors;
  * the overall gain and error, Eqs. (B28)-(B31), by counting the same detectors
    over a numerically integrated relative phase;
  * the published curves, Lo, Curty and Qi (2012), Fig. 2, read from the figure.
"""

from __future__ import annotations

import importlib.util
import itertools
import json
import math
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("protocol_rates", ROOT / "tools" / "protocol_rates.py")
pr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pr)

GOLDEN = json.loads(pr.GOLDEN.read_text(encoding="utf-8"))

# ---- exact linear optics ---------------------------------------------------
# Output modes of the relay: 0 = port 1 H, 1 = port 1 V, 2 = port 2 H, 3 = port 2 V.
PSI_PLUS = ({0, 1}, {2, 3})
PSI_MINUS = ({0, 3}, {1, 2})
S2 = math.sqrt(0.5)
STATES = {("Z", 0): (1.0, 0.0), ("Z", 1): (0.0, 1.0), ("X", 0): (S2, S2), ("X", 1): (S2, -S2)}


def _rotate(theta, v):
    c, s = math.cos(theta), math.sin(theta)
    return c * v[0] - s * v[1], s * v[0] + c * v[1]


def _pair_probabilities(pol_a, pol_b):
    """P(photon-number pattern on the four modes), both photons arriving at a 50:50 BS."""
    a = [S2 * pol_a[0], S2 * pol_a[1], S2 * pol_a[0], S2 * pol_a[1]]
    b = [S2 * pol_b[0], S2 * pol_b[1], -S2 * pol_b[0], -S2 * pol_b[1]]
    out = {}
    for i in range(4):
        for j in range(i, 4):
            p = 2 * (a[i] * b[i]) ** 2 if i == j else (a[i] * b[j] + a[j] * b[i]) ** 2
            if p > 1e-15:
                out[(i, j)] = p
    return out


def _clicks(photon_modes, wanted, pd):
    p = 1.0
    for m in range(4):
        if m in photon_modes:
            if m not in wanted:
                return 0.0
        else:
            p *= pd if m in wanted else (1 - pd)
    return p


def _outcomes(sa, sb, eta_a, eta_b, pd, theta_a=0.0, theta_b=0.0):
    pa, pb = _rotate(theta_a, sa), _rotate(theta_b, sb)
    result = {"+": 0.0, "-": 0.0}
    for name, sets in (("+", PSI_PLUS), ("-", PSI_MINUS)):
        for wanted in sets:
            for (i, j), p in _pair_probabilities(pa, pb).items():
                result[name] += eta_a * eta_b * p * _clicks({i, j}, wanted, pd)
            for eta, pol in ((eta_a * (1 - eta_b), pa), (eta_b * (1 - eta_a), pb)):
                for i, amp in enumerate((S2 * pol[0], S2 * pol[1], S2 * pol[0], S2 * pol[1])):
                    if amp * amp > 1e-15:
                        result[name] += eta * amp * amp * _clicks({i}, wanted, pd)
            result[name] += (1 - eta_a) * (1 - eta_b) * _clicks(set(), wanted, pd)
    return result


def _basis_yield_and_error(basis, eta_a, eta_b, pd, theta_a=0.0, theta_b=0.0):
    total = err = 0.0
    for a, b in itertools.product((0, 1), repeat=2):
        r = _outcomes(STATES[(basis, a)], STATES[(basis, b)], eta_a, eta_b, pd, theta_a, theta_b)
        total += 0.25 * (r["+"] + r["-"])
        if basis == "Z":
            if a == b:
                err += 0.25 * (r["+"] + r["-"])
        else:
            err += 0.25 * (r["-"] if a == b else r["+"])
    return total, err


CHANNELS = [(1.0, 1.0, 0.0), (0.3, 0.1, 0.0), (0.3, 0.1, 1e-5), (0.01, 0.002, 1e-6), (1e-3, 1e-3, 3e-6), (0.05, 0.05, 1e-3)]


@pytest.mark.parametrize("eta_a,eta_b,pd", CHANNELS)
def test_y11_is_the_yield_of_exact_two_photon_optics(eta_a, eta_b, pd):
    for basis in "ZX":
        y, _ = _basis_yield_and_error(basis, eta_a, eta_b, pd)
        assert y == pytest.approx(pr.mdi_y11(eta_a, eta_b, pd), rel=1e-9)


@pytest.mark.parametrize("eta_a,eta_b,pd", CHANNELS)
def test_e11_at_no_misalignment_is_the_x_basis_error_of_exact_optics(eta_a, eta_b, pd):
    y, err = _basis_yield_and_error("X", eta_a, eta_b, pd)
    if y > 0:
        assert err / y == pytest.approx(pr.mdi_e11(eta_a, eta_b, pd, 0.0), rel=1e-9, abs=1e-12)


def test_the_z_basis_needs_opposite_bits_and_the_x_basis_loses_half():
    # Hong-Ou-Mandel: equal Z inputs bunch, and give no two-detector event.
    equal = _outcomes(STATES[("Z", 0)], STATES[("Z", 0)], 1, 1, 0)
    assert equal["+"] + equal["-"] == pytest.approx(0)
    opposite = _outcomes(STATES[("Z", 0)], STATES[("Z", 1)], 1, 1, 0)
    assert opposite["+"] == pytest.approx(0.5)
    assert opposite["-"] == pytest.approx(0.5)
    same_x = _outcomes(STATES[("X", 0)], STATES[("X", 0)], 1, 1, 0)
    assert same_x["+"] == pytest.approx(0.5)
    assert same_x["-"] == pytest.approx(0)
    opposite_x = _outcomes(STATES[("X", 0)], STATES[("X", 1)], 1, 1, 0)
    assert opposite_x["+"] == pytest.approx(0)
    assert opposite_x["-"] == pytest.approx(0.5)
    mixed = _outcomes(STATES[("Z", 0)], STATES[("X", 0)], 1, 1, 0)
    assert mixed["+"] == pytest.approx(0.25)
    assert mixed["-"] == pytest.approx(0.25)


@pytest.mark.parametrize("theta_a,theta_b", [(0.05, 0.05), (0.05, -0.05), (0.1, 0.0), (0.12, 0.03)])
def test_small_misalignment_tracks_e_d_in_the_x_basis(theta_a, theta_b):
    e_d = math.sin(theta_a) ** 2 + math.sin(theta_b) ** 2
    y, err = _basis_yield_and_error("X", 1, 1, 0, theta_a, theta_b)
    # First order in e_d, which is what Eq. (A11) claims.
    assert err / y == pytest.approx(e_d, abs=2 * e_d**2 + 1e-4 + e_d * 0.35)


# ---- the overall gain, by counting detectors --------------------------------
def _click(mean_photons, pd):
    return 1 - (1 - pd) * math.exp(-mean_photons)


def _two_detector_event(i1, i2, v1, v2, pd):
    """P(exactly one of the H pair and exactly one of the V pair fire)."""
    def one_of_two(m1, m2):
        p1, p2 = _click(m1, pd), _click(m2, pd)
        return p1 * (1 - p2) + p2 * (1 - p1)
    return one_of_two(i1, i2) * one_of_two(v1, v2)


def _counted_gain_and_error(eta_a, eta_b, mu_a, mu_b, pd, e_d, steps=4000):
    """Z basis, phase-randomised coherent states, threshold detectors, by direct count."""
    a, b = eta_a * mu_a, eta_b * mu_b
    # Different modes: one pulse in each polarisation, no interference.
    q_c = 0.5 * _two_detector_event(a / 2, a / 2, b / 2, b / 2, pd)
    # Same mode: both pulses in one polarisation, interfering at the BS, averaged
    # over the relative phase; the other polarisation sees only background.
    q_e = 0.0
    for k in range(steps):
        phi = 2 * math.pi * (k + 0.5) / steps
        cross = math.sqrt(a * b) * math.cos(phi)
        q_e += _two_detector_event((a + b) / 2 + cross, (a + b) / 2 - cross, 0.0, 0.0, pd)
    q_e *= 0.5 / steps
    q = q_c + q_e
    return q, (e_d * q_c + (1 - e_d) * q_e) / q


@pytest.mark.parametrize("eta_a,eta_b,mu_a,mu_b,pd,e_d", [
    (0.145, 0.145, 0.6, 0.6, 3e-6, 0.015),
    (0.0145, 0.0145, 0.55, 0.55, 3e-6, 0.015),
    (0.00145, 0.00145, 0.5, 0.5, 3e-6, 0.015),
    (0.3, 0.03, 0.2, 2.0, 1e-6, 0.02),
    (0.5, 0.5, 1.0, 1.0, 1e-3, 0.0),
])
def test_the_closed_form_gain_is_what_the_detectors_count(eta_a, eta_b, mu_a, mu_b, pd, e_d):
    q, e = pr.mdi_gain_rect(eta_a, eta_b, mu_a, mu_b, pd, e_d)
    counted_q, counted_e = _counted_gain_and_error(eta_a, eta_b, mu_a, mu_b, pd, e_d)
    assert q == pytest.approx(counted_q, rel=1e-6)
    assert e == pytest.approx(counted_e, rel=1e-6)


# ---- thermal BBM92, summed term by term -------------------------------------
def test_the_thermal_gain_is_the_sum_of_its_photon_numbers():
    eta_a, eta_b, lam, y0 = 0.05, 0.02, 0.06, 6.02e-6
    total = 0.0
    for n in range(400):
        p = (n + 1) * lam**n / (1 + lam) ** (n + 2)  # Ma, Fung and Lo, Eq. (5)
        total += p * (1 - (1 - y0) * (1 - eta_a) ** n) * (1 - (1 - y0) * (1 - eta_b) ** n)
    assert pr.bbm92_gain_qber(eta_a, eta_b, lam, y0, 0.015)[0] == pytest.approx(total, rel=1e-10)


# ---- the published anchors ---------------------------------------------------
def test_bb84_reproduces_the_golden_vector_of_keyrate_md():
    # docs/keyrate.md section 6: R = 2.555e-3 bits per pulse at q = 1/2.
    assert 0.5 * pr.bb84_rate(0.045, 0.48, 1.7e-6, 0.033, 1.22) == pytest.approx(2.555e-3, rel=1e-3)


def _crossing(fn, level, lo=0.0, hi=500.0):
    while hi - lo > 0.05:
        mid = (lo + hi) / 2
        if fn(mid) > level:
            lo = mid
        else:
            hi = mid
    return lo


def test_the_mdi_curve_of_lo_curty_qi_fig_2():
    # Read from the figure: about 1.5e-4 at 0 km, about 1.2e-6 at 100 km, and 1e-10
    # at about 222 km. The figure's rate carries the 1/4 of balanced bases with a
    # Z-only key. Their misalignment is two rotations; this is Ma and Razavi's
    # simpler model, which ends some kilometres later (docs/keyrate.md section 9).
    r = lambda length: 0.25 * pr.curve_point("mdi", length, pr.PUBLISHED)[0]  # noqa: E731
    assert 1.2e-4 < r(0.0) < 1.8e-4
    assert 0.9e-6 < r(100.0) < 1.6e-6
    assert 215.0 < _crossing(r, 1e-10) < 235.0


def test_the_entanglement_curve_of_lo_curty_qi_fig_2():
    # Read from the figure: about 8e-4 at 0 km, and 1e-10 at about 300 km, with the
    # two-detector background 6.02e-6 per side and q = 1.
    r = lambda length: pr.curve_point("bbm92", length, pr.PUBLISHED)[0]  # noqa: E731
    assert 6e-4 < r(0.0) < 1.1e-3
    assert 290.0 < _crossing(r, 1e-10) < 312.0


def test_the_repeaterless_bound_is_about_1_44_eta_at_high_loss():
    # Pirandola et al. (2017), Eq. (20).
    assert pr.plob(1e-4) == pytest.approx(1.44 * 1e-4, rel=2e-3)


def test_the_golden_file_is_what_the_reference_writes():
    assert json.loads(json.dumps(pr.golden())) == GOLDEN
