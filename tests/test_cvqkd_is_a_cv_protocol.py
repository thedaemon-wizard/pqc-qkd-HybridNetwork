"""CV-QKD must be judged by continuous-variable criteria, not BB84's.

The public demo ran with `SIMULATOR_BACKEND=cvqkd` and emitted no key at all:
165 rounds, 165 aborts, QBER reported as 0.443. Four separate defects combined
to produce that, and each is pinned below.

  1. The channel was applied twice -- `LossChannel(T)` followed by
     `ThermalLossChannel(T, xi)` -- so the transmittance was squared.
  2. The excess noise `xi` was passed as Strawberry Fields' `nbar`, which is a
     different quantity appearing in a different place in the variance.
  3. Alice's modulation was drawn with sigma = sqrt(V_A/2) when hbar = 2 needs
     sqrt(V_A)/2, putting twice the intended variance on the channel.
  4. Acceptance was gated on BB84's 11 % QBER threshold applied to the sign
     agreement of a homodyne quadrature -- a quantity that tends to 0.5 under
     loss no matter how good the channel is. Reverse reconciliation exists
     precisely because that number is not an error rate.

And, underneath all of it, the Holevo bound was a scalar stand-in that exceeded
I(A:B) for every physically sensible parameter set, so the rate was identically
zero and no round could ever have produced a key even with the gate removed.

These tests do not need Strawberry Fields: the parts that were wrong are the
closed-form model and the unit conversions, which are pure functions.
"""
from __future__ import annotations

import importlib
import math

import pytest
from conftest import load_service_app

load_service_app("bb84-kme", "bb84_kme_app")
cv = importlib.import_module("bb84_kme_app.backends.cvqkd_backend")

# Representative GG02 operating point: Gaussian modulation of 4 SNU, 1 % excess
# noise, 95 % reconciliation efficiency.
V_A, XI, BETA = 4.0, 0.01, 0.95


def transmittance(km: float, db_per_km: float = 0.2) -> float:
    return 10.0 ** (-db_per_km * km / 10.0)


class TestSecretKeyRate:
    def test_a_lossless_channel_yields_a_positive_rate(self):
        """The check the old bound could not pass, at any distance."""
        assert cv.gg02_asymptotic_skr(V_A=V_A, T=1.0, xi=XI, beta=BETA) > 0.5

    def test_rate_falls_monotonically_with_distance(self):
        rates = [
            cv.gg02_asymptotic_skr(V_A=V_A, T=transmittance(km), xi=XI, beta=BETA)
            for km in (0, 10, 25, 50, 80)
        ]
        assert rates == sorted(rates, reverse=True)
        assert all(r > 0 for r in rates), f"key vanishes over fibre alone: {rates}"

    def test_rate_falls_as_excess_noise_rises_and_reaches_a_null_key_point(self):
        T = transmittance(25)
        rates = [cv.gg02_asymptotic_skr(V_A=V_A, T=T, xi=x, beta=BETA)
                 for x in (0.0, 0.05, 0.10, 0.30, 1.0)]
        assert rates == sorted(rates, reverse=True)
        assert rates[0] > 0, "a noiseless channel must produce key"
        assert rates[-1] == 0.0, "no null-key threshold: the bound is not binding"

    def test_reconciliation_efficiency_scales_the_rate(self):
        T = transmittance(25)
        perfect = cv.gg02_asymptotic_skr(V_A=V_A, T=T, xi=XI, beta=1.0)
        realistic = cv.gg02_asymptotic_skr(V_A=V_A, T=T, xi=XI, beta=BETA)
        assert perfect > realistic > 0

    def test_the_holevo_bound_actually_binds(self):
        """It must subtract something, and not everything.

        The previous bound failed in both directions at once: it was large
        enough to zero the rate everywhere, which also made it useless as a
        bound because no parameter change could ever matter.
        """
        T = transmittance(25)
        chi_line = (1 - T) / T + XI
        V = V_A + 1.0
        i_ab = 0.5 * math.log2((V + chi_line) / (1 + chi_line))
        rate = cv.gg02_asymptotic_skr(V_A=V_A, T=T, xi=XI, beta=1.0)
        assert 0 < rate < i_ab, "Eve's information is either ignored or overwhelming"

    @pytest.mark.parametrize("bad", [
        {"T": 0.0}, {"T": -0.1}, {"V_A": 0.0}, {"beta": 0.0},
    ])
    def test_degenerate_inputs_give_no_key_rather_than_an_exception(self, bad):
        kw = {"V_A": V_A, "T": 0.5, "xi": XI, "beta": BETA} | bad
        assert cv.gg02_asymptotic_skr(**kw) == 0.0


class TestThermalPhotonConversion:
    """`xi` and `nbar` are not the same number.

    Verified against Strawberry Fields itself: a homodyne x after
    ThermalLossChannel(T, nbar) has variance T + (1-T)(2*nbar+1), measured as
    1.6136 for T=0.4, nbar=0.5 against a predicted 1.6000.
    """

    @pytest.mark.parametrize("T", [0.1, 0.3, 0.631, 0.9])
    @pytest.mark.parametrize("xi", [0.0, 0.01, 0.1])
    def test_conversion_reproduces_the_intended_output_variance(self, T, xi):
        nbar = cv.thermal_photons_for_excess_noise(T, xi)
        simulated = T + (1 - T) * (2 * nbar + 1)   # what the channel produces
        intended = 1.0 + T * xi                    # the CV-QKD convention
        assert simulated == pytest.approx(intended, rel=1e-12)

    def test_passing_xi_directly_is_the_wrong_number(self):
        """Pin the original defect, so the shortcut cannot come back."""
        T, xi = 0.126, 0.01
        wrong = T + (1 - T) * (2 * xi + 1)
        right = T + (1 - T) * (2 * cv.thermal_photons_for_excess_noise(T, xi) + 1)
        assert wrong != pytest.approx(right)
        assert right == pytest.approx(1.0 + T * xi)

    def test_a_lossless_channel_adds_no_thermal_photons(self):
        assert cv.thermal_photons_for_excess_noise(1.0, 0.1) == 0.0


class TestChannelEstimation:
    """The acceptance decision must follow the channel that was simulated."""

    @staticmethod
    def _synthetic(T, xi, n=200_000, seed=7):
        import numpy as np
        rng = np.random.default_rng(seed)
        alice_x = rng.normal(0.0, math.sqrt(V_A), size=n)   # variance V_A in SNU
        noise = rng.normal(0.0, math.sqrt(1.0 + T * xi), size=n)
        return alice_x, math.sqrt(T) * alice_x + noise

    @pytest.mark.parametrize("T", [0.126, 0.316, 0.631])
    @pytest.mark.parametrize("xi", [0.0, 0.05])
    def test_recovers_the_channel_it_was_given(self, T, xi):
        alice_x, bob_x = self._synthetic(T, xi)
        T_est, xi_est = cv.estimate_channel(alice_x, bob_x)
        assert T_est == pytest.approx(T, rel=0.05)
        assert xi_est == pytest.approx(xi, abs=0.05)

    def test_an_estimated_channel_produces_the_expected_rate(self):
        T = 0.316
        alice_x, bob_x = self._synthetic(T, 0.01)
        T_est, xi_est = cv.estimate_channel(alice_x, bob_x)
        from_estimate = cv.gg02_asymptotic_skr(V_A=V_A, T=T_est, xi=xi_est, beta=BETA)
        from_truth = cv.gg02_asymptotic_skr(V_A=V_A, T=T, xi=0.01, beta=BETA)
        assert from_estimate == pytest.approx(from_truth, rel=0.2)
        assert from_estimate > 0

    def test_an_uncorrelated_record_yields_no_key(self):
        """Eve replacing the channel entirely must not be accepted."""
        import numpy as np
        rng = np.random.default_rng(1)
        alice_x = rng.normal(0.0, math.sqrt(V_A), size=100_000)
        bob_x = rng.normal(0.0, 1.0, size=100_000)
        T_est, xi_est = cv.estimate_channel(alice_x, bob_x)
        assert cv.gg02_asymptotic_skr(V_A=V_A, T=T_est, xi=xi_est, beta=BETA) == 0.0

    def test_no_modulation_is_handled_without_dividing_by_zero(self):
        import numpy as np
        z = np.zeros(1000)
        assert cv.estimate_channel(z, z) == (0.0, 0.0)


def test_sign_disagreement_is_not_an_error_rate_to_threshold():
    """Why gating on BB84's 11 % was the decisive mistake.

    For a Gaussian-modulated quadrature seen through loss, the sign of Bob's
    homodyne outcome disagrees with Alice's at a rate approaching 0.5 -- the
    signal spends much of its time within a shot noise of the origin. The rate
    below is far above BB84's abort threshold while the channel is good enough
    to distil key, which is exactly the contradiction the demo was stuck in.
    """
    T = 0.126
    sigma_signal = math.sqrt(T) * math.sqrt(V_A)
    sigma_noise = math.sqrt(1.0 + T * XI)
    disagreement = math.atan(sigma_noise / sigma_signal) / math.pi

    assert disagreement > 0.11, "the premise of the DV gate"
    assert cv.gg02_asymptotic_skr(V_A=V_A, T=T, xi=XI, beta=BETA) > 0, (
        "the channel yields key despite a sign disagreement above 11 %"
    )
