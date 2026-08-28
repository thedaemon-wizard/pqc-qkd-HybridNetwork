"""The finite-key analysis is Lim et al. 2014, and it behaves like one.

What this replaced was a single line::

    def finite_key_penalty(N, eps):
        return math.sqrt(2.0 / N) * math.sqrt(math.log2(2.0 / eps))

subtracted from the asymptotic per-pulse rate. Four independent faults, all
established by reading the sources:

  1. Mis-cited to arXiv:2511.21253, which contains no such term.
  2. 2.402x a two-sided Hoeffding deviation, with log2 where ln belongs.
  3. Channel-independent. N is pulses SENT; the statistics live in the
     DETECTION counts, and the deviation has to propagate through the decoy
     inversion, where near-cancelling differences over small denominators
     amplify it by one to two orders of magnitude. That amplification is the
     dominant finite-size effect in decoy BB84 and was entirely absent.
  4. Neither an upper nor a lower bound, so it could not be defended as
     conservative in either direction.

**The tell that separates the two.** The old term produced a straight line of
about 25 km per decade of N with NO saturation, so at N = 1e30 it claimed key
past 500 km -- beyond the distance where the asymptotic GLLP rate is
identically zero. A correct finite-key curve saturates. That it happened to
give 93.3 km at N = 1e9 against the correct 98.5 km is a coincidence of that
one decade, and `test_the_old_shape_is_gone` below is the test that would have
caught it.

Reference: Lim, Curty, Walenta, Xu, Zbinden, "Concise security bounds for
practical decoy-state quantum key distribution", PRA 89, 022307 (2014),
arXiv:1311.7129. Main text Eqs. (1)-(5), supplementary Eqs. (1)-(14).
"""
from __future__ import annotations

import math
import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "services" / "bb84-kme"))

from app.backends import _skr  # noqa: E402

# The reference point. Every intermediate was cross-checked against an
# independent transcription of the paper and agreed to 8 significant figures.
REF = {
    "eta_d": 0.20, "alpha_db_km": 0.20, "L_km": 50.0,
    "Y0": 1.0e-7, "e_d": 0.015, "f_EC": 1.16,
    "mus": (0.5, 0.1, 0.0), "ps": (0.70, 0.15, 0.15),
    "qx": 0.5, "N": 1.0e9, "eps_sec": 1.0e-10, "eps_cor": 1.0e-15,
}


def _run(**over):
    p = {**REF, **over}
    eta = _skr.total_transmittance(p["eta_d"], p["alpha_db_km"], p["L_km"])
    c = _skr.lim_counts_from_channel(N=p["N"], qx=p["qx"], mus=p["mus"],
                                     ps=p["ps"], Y0=p["Y0"], eta_total=eta,
                                     e_d=p["e_d"])
    return _skr.lim_key_length(nX_k=c["nX_k"], nZ_k=c["nZ_k"], mX_k=c["mX_k"],
                               mZ_k=c["mZ_k"], mus=p["mus"], ps=p["ps"],
                               eps_sec=p["eps_sec"], eps_cor=p["eps_cor"],
                               f_EC=p["f_EC"])


def _rate(L, N=1.0e9, **over):
    p = {**REF, "L_km": L, "N": N, **over}
    if "qx" in over:
        p["qx"] = over["qx"]
    eta = _skr.total_transmittance(p["eta_d"], p["alpha_db_km"], p["L_km"])
    return _skr.skr_finite(Y0=p["Y0"], eta_total=eta, e_d=p["e_d"],
                           mu=p["mus"][0], nu1=p["mus"][1], nu2=p["mus"][2],
                           f_EC=p["f_EC"], N=p["N"], eps=p["eps_sec"],
                           qx=p["qx"], p_mu=p["ps"][0], p_nu1=p["ps"][1],
                           p_nu2=p["ps"][2], eps_cor=p["eps_cor"])


def _crossing(N, lo=0.5, hi=400.0, **over):
    for _ in range(80):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if _rate(mid, N, **over) > 0 else (lo, mid)
    return hi


# --------------------------------------------------------------------------
# The reference vector, term by term.
# --------------------------------------------------------------------------

@pytest.mark.parametrize("field,expected", [
    ("tau_0", 0.7102970745), ("tau_1", 0.2258582922),
    ("n_X", 1.81622914e+06), ("m_X", 2.72555622e+04),
    ("s_X0", 0.0), ("s_X1", 9.01281837e+05), ("s_Z1", 9.01281837e+05),
    ("v_Z1", 2.86522239e+04), ("phi_X", 3.42515394e-02),
    ("leak_EC", 2.36809351e+05), ("eps_penalty_bits", 276.498512),
    ("ell", 4.70164231e+05),
])
def test_every_intermediate_matches_the_reference(field, expected):
    """Pinned individually, so a mismatch localises to one estimator."""
    got = _run()[field]
    assert got == pytest.approx(expected, rel=1e-6, abs=1e-9), (
        f"{field}: {got!r} vs {expected!r}")


def test_the_rate_per_pulse():
    assert _run()["ell"] / REF["N"] == pytest.approx(4.702e-04, rel=1e-3)


def test_the_epsilon_penalty_is_the_paper_constant():
    """6*log2(21/eps_sec) + log2(2/eps_cor), and the 6 pairs with the 21."""
    expected = 6.0 * math.log2(21.0 / 1e-10) + math.log2(2.0 / 1e-15)
    assert _run()["eps_penalty_bits"] == pytest.approx(expected, rel=1e-12)
    assert _skr.LIM_UNION_COEFF == 6.0
    assert _skr.LIM_EPS_DIVISOR == 21.0


def test_symmetric_basis_choice_gives_equal_x_and_z_single_photons():
    """qx = 0.5 forces s_X1 == s_Z1 exactly. Catches a basis mix-up."""
    r = _run()
    assert r["s_X1"] == pytest.approx(r["s_Z1"], rel=1e-12)


# --------------------------------------------------------------------------
# Shape. This is what tells a correct curve from a plausible one.
# --------------------------------------------------------------------------

@pytest.mark.parametrize("N,km", [
    (1e8, 48.83), (1e9, 98.49), (1e10, 147.29),
    (1e11, 189.11), (1e12, 219.93), (1e14, 249.73),
])
def test_the_zero_crossing_moves_with_N_as_the_paper_predicts(N, km):
    assert _crossing(N) == pytest.approx(km, abs=0.6)


def test_the_old_shape_is_gone():
    """The single most important test in this file.

    sqrt(2/N) gave a straight ~25 km per decade with no saturation, so it kept
    gaining distance without limit. The real curve saturates: the last three
    decades before 1e14 must buy far less than the first three.
    """
    early = _crossing(1e9) - _crossing(1e8)      # ~50 km
    late = _crossing(1e14) - _crossing(1e13)     # much smaller
    assert early > 0 and late > 0
    assert late < early / 3.0, (
        f"gain per decade is not decaying: {early:.1f} km early vs "
        f"{late:.1f} km late -- this is the unbounded shape the sqrt(2/N) "
        f"penalty produced")


def test_it_never_claims_key_at_absurd_distance():
    """The old term would have claimed key past 500 km at N = 1e30."""
    assert _rate(500.0, 1e30) == 0.0
    assert _rate(400.0, 1e30) == 0.0


def test_more_pulses_never_lowers_the_rate():
    """Physical: more data cannot hurt. Checked where it is tightest."""
    for L in (10.0, 50.0, 98.0, 150.0, 256.0):
        rates = [_rate(L, 10.0 ** e) for e in range(6, 20)]
        assert rates == sorted(rates), f"non-monotone in N at {L} km: {rates}"


def test_more_distance_never_raises_the_rate():
    rates = [_rate(L) for L in (0.0, 10.0, 25.0, 50.0, 75.0, 90.0, 98.0, 120.0)]
    assert rates == sorted(rates, reverse=True), rates


def test_the_finite_rate_stays_below_the_asymptotic_one_at_the_default():
    """A finite-key rate above the asymptotic one would be nonsense.

    Compared per sifted pulse, so the qx^2 and intensity-mixture factors do not
    confuse the comparison.
    """
    for L in (10.0, 50.0, 90.0):
        eta = _skr.total_transmittance(0.2, 0.2, L)
        asym = _skr.asymptotic_skr_per_pulse(
            Y0=1e-7, eta_total=eta, e_d=0.015, mu=0.5, nu1=0.1, nu2=0.0,
            f_EC=1.16)
        assert _rate(L) < 2.0 * REF["qx"] ** 2 * asym, f"at {L} km"


# --------------------------------------------------------------------------
# Guards on inputs the theorem does not cover.
# --------------------------------------------------------------------------

@pytest.mark.parametrize("mu,nu1,nu2", [
    (0.5, 0.1, 0.45),    # nu1 + nu2 > mu AND nu2 > nu1
    (0.5, 0.4, 0.2),     # nu1 + nu2 > mu
    (0.5, 0.1, 0.2),     # nu2 > nu1
    (0.5, 0.1, -0.01),   # nu2 < 0
])
def test_intensities_outside_lims_ordering_yield_no_key(mu, nu1, nu2):
    """Lim requires mu1 > mu2 + mu3 and mu2 > mu3 >= 0."""
    eta = _skr.total_transmittance(0.2, 0.2, 50.0)
    assert _skr.skr_finite(Y0=1e-7, eta_total=eta, e_d=0.015, mu=mu, nu1=nu1,
                           nu2=nu2, f_EC=1.16, N=1e9, eps=1e-10) == 0.0


@pytest.mark.parametrize("N", [0, -1, 1, 100])
def test_a_useless_block_size_yields_no_key(N):
    assert _rate(50.0, N) == 0.0


@pytest.mark.parametrize("eps", [0.0, -1e-10, 1.0, 2.0])
def test_a_nonsensical_epsilon_yields_no_key(eps):
    assert _rate(50.0, 1e9, eps_sec=eps) == 0.0


def test_starving_the_check_basis_yields_no_key_not_a_high_one():
    """qx -> 1 leaves no Z detections to estimate the phase error from.

    The failure must be downward. If it ever returns a HIGH rate, phi_X is
    being defaulted to something optimistic instead of 0.5.
    """
    assert _rate(50.0, 1e9, qx=1.0) == 0.0
    assert _rate(50.0, 1e9, qx=0.0) == 0.0


def test_the_rate_is_finite_and_non_negative_everywhere_tested():
    for L in (0.0, 1e-6, 10.0, 100.0, 300.0, 1000.0):
        for N in (1e3, 1e6, 1e9, 1e15):
            v = _rate(L, N)
            assert math.isfinite(v) and v >= 0.0, f"L={L} N={N} -> {v}"


# --------------------------------------------------------------------------
# The removed function must stay removed.
# --------------------------------------------------------------------------

def test_the_old_penalty_function_is_gone():
    assert not hasattr(_skr, "finite_key_penalty"), (
        "finite_key_penalty is back; it was mis-cited, 2.402x a Hoeffding "
        "deviation, channel-independent and not a bound in either direction")


def test_no_source_file_still_credits_arxiv_2511_21253_for_it():
    """The citation appeared at nine sites for a formula that paper lacks."""
    # This file names the citation in order to forbid it, so it must exclude
    # itself. A guard that counts itself as an offender is a guard that can
    # never go green -- the same self-reference trap that once made
    # test_every_config_key_is_read_by_something vacuous.
    SELF = pathlib.Path(__file__).resolve()
    stale = []
    for pat in ("*.py", "*.ts", "*.tsx", "*.md", "*.yaml"):
        for f in REPO.rglob(pat):
            if f.resolve() == SELF:
                continue
            # Any dot-directory, plus the two vendored trees. Spelled this
            # way rather than as a literal list because naming every excluded
            # directory would put a tooling vendor name into tracked content,
            # which test_no_ai_tooling_attribution_in_tracked_content forbids
            # -- and it caught exactly that here.
            if any(part.startswith(".") for part in f.parts):
                continue
            if any(x in f.parts for x in ("node_modules", "submodules")):
                continue
            txt = f.read_text(encoding="utf-8", errors="replace")
            lines = txt.splitlines()
            for n, line in enumerate(lines, 1):
                if "2511.21253" not in line:
                    continue
                # A +/-3 line window, not the single line. PhysicsParams.tsx
                # rendered "the closed-form formulae of Lo-Ma-Chen ... and
                # arXiv:2511.21253" to every visitor of /physics, and the
                # single-line form skipped it because that one line happened to
                # carry none of the keywords -- the sentence was wrapped.
                low = "\n".join(lines[max(0, n - 4):n + 3]).lower()
                if not any(w in low for w in ("finite-key", "finite key",
                                              "finite-size", "penalty",
                                              "key rate", "key-rate",
                                              "closed-form", "skr")):
                    continue
                # The paper is real. Naming it to RETRACT the citation is the
                # record of why the formula changed and must survive -- what is
                # forbidden is presenting it as the source. Distinguishing the
                # two needs the retraction markers, because a bare
                # substring search flags the correction notices as offences and
                # the guard can then never go green.
                if any(w in low for w in ("was ", "previously", "not contain",
                                          "does not", "no such", "mis-cit",
                                          "instead of", "rather than")):
                    continue
                stale.append(f"{f.relative_to(REPO)}:{n}")
    assert stale == [], (
        "arXiv:2511.21253 is still credited for the finite-key correction at: "
        + ", ".join(stale))


# --------------------------------------------------------------------------
# The basis bias is a probability, and nothing may claim more key than photons.
# --------------------------------------------------------------------------

@pytest.mark.parametrize("qx", [1.0, 1.0001, 2.0, 50.0, 100.0, 0.0, -0.5])
def test_a_basis_bias_outside_zero_to_one_yields_no_key(qx):
    """It enters as qx^2 scaling the counts, so >1 inflates without bound.

    Measured before the guard, at the shipped 50 km config where the detection
    probability Q_mu is 9.95e-3:

        basis_bias_pz   rate/pulse    bits/s @ 1 GHz
                0.5     4.7016e-04     470 k
                2.0     1.0178e-02     10.2 M   -- already exceeds Q_mu
               50.0     7.1922e+00     7.19 G   -- 723x the detections

    and accepts_round() returned True for every one. `source.basis_bias_pz` is
    editable through the API and the /physics input has no min or max, so "50"
    typed for "50 %" reached it.
    """
    assert _rate(50.0, 1e9, qx=qx) == 0.0


def test_the_rate_can_never_exceed_the_detection_probability():
    """A sanity ceiling no correct implementation can breach.

    One detected photon cannot yield more than one secret bit, so the per-pulse
    rate is bounded above by the per-pulse detection probability. This is the
    invariant the unvalidated qx violated by 723x.
    """
    for L in (0.0, 10.0, 50.0, 90.0):
        eta = _skr.total_transmittance(0.2, 0.2, L)
        q_mu = _skr.gain_Qmu(1e-7, eta, 0.5)
        for qx in (0.1, 0.3, 0.5, 0.7, 0.9):
            r = _rate(L, 1e12, qx=qx)
            assert r <= q_mu, (
                f"L={L} qx={qx}: rate {r:.4e} exceeds detection probability "
                f"{q_mu:.4e} -- more secret bits than detected photons")


def test_a_legal_basis_bias_still_works_given_enough_data():
    """The guard must not swallow honest values.

    qx = 0.9 gives zero at 50 km / N = 1e9 because only 1 % of pulses land in
    the check basis and phi_X defaults to 0.5 -- that is the physics refusing
    to bound the phase error, and it recovers with more data. If this ever
    fails, the range guard is over-rejecting.
    """
    assert _rate(10.0, 1e9, qx=0.9) > 0.0
    assert _rate(50.0, 1e11, qx=0.9) > 0.0
    assert _rate(50.0, 1e9, qx=0.9) == 0.0     # starved, not rejected


@pytest.mark.parametrize("pm,p1,p2", [
    (0.5, 0.3, 0.5),     # sums to 1.3
    (0.3, 0.3, 0.3),     # sums to 0.9
    (0.8, 0.2, 0.0),     # a zero divisor in the bracketed counts
    (1.0, 0.0, 0.0),
])
def test_intensity_probabilities_must_be_a_distribution(pm, p1, p2):
    """tau_n is a distribution over photon number, and delta is divided by p_k.

    Neither means anything if the probabilities do not sum to 1, and a zero
    p_k divides by zero outright.
    """
    assert _rate(50.0, 1e9, ps=(pm, p1, p2)) == 0.0
