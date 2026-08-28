"""Shared SKR helpers: Lo-Ma 2005 asymptotic decoy bound + Lim et al. 2014
finite-key analysis (PRA 89, 022307, arXiv:1311.7129).

Used by every backend that needs a science-grounded channel model, OR a
secret-key-rate sanity check, without invoking heavy simulators.
"""
from __future__ import annotations

import math
from collections.abc import Sequence


def H2(x: float) -> float:
    return -x * math.log2(x) - (1 - x) * math.log2(1 - x) if 0.0 < x < 1.0 else 0.0


def total_transmittance(eta_d: float, alpha_db_per_km: float, L_km: float) -> float:
    return eta_d * 10 ** (-alpha_db_per_km * L_km / 10.0)


def gain_Qmu(Y0: float, eta_total: float, intensity: float) -> float:
    """Q_μ = Y0 + 1 - exp(-η·μ)  (Lo-Ma 2005 eq 32)."""
    return Y0 + 1.0 - math.exp(-eta_total * intensity)


def qber_Emu(Y0: float, eta_total: float, e_d: float, intensity: float) -> float:
    """E_μ = [Y0/2 + e_d·(1 - exp(-η·μ))] / Q_μ."""
    q = gain_Qmu(Y0, eta_total, intensity)
    if q <= 0.0:
        return 0.5
    return (Y0 / 2.0 + e_d * (1.0 - math.exp(-eta_total * intensity))) / q


def asymptotic_skr_per_pulse(
    *, Y0: float, eta_total: float, e_d: float, mu: float, nu1: float, nu2: float,
    f_EC: float,
) -> float:
    """Lo-Ma two-decoy lower bound on the asymptotic SKR (per pulse)."""
    Q_mu = gain_Qmu(Y0, eta_total, mu)
    E_mu = qber_Emu(Y0, eta_total, e_d, mu)
    Q_nu1 = gain_Qmu(Y0, eta_total, nu1)
    Q_nu2 = gain_Qmu(Y0, eta_total, nu2) if nu2 > 0 else Y0
    E_nu1 = qber_Emu(Y0, eta_total, e_d, nu1)
    if nu1 <= 0 or mu - nu1 <= 0:
        return 0.0
    # Ma et al. PRA 72, 012326 (2005), Eq. (18)/(34). The denominator is the
    # GENERAL two-decoy form. It previously read `mu * nu1 - nu1 * nu1`, which
    # is that expression with nu2 = 0 substituted -- while the numerator kept
    # its (nu1^2 - nu2^2) term, so the two halves assumed different nu2. The
    # paper's validity condition is nu1 + nu2 < mu, not nu2 == 0.
    #
    # Correct at the shipped default (nu2 = 0.0) and wrong above it, which is
    # why 301 tests passed: every case pinned nu2 = 0.0. The optimiser grid in
    # config/qkd_params.yaml does search nu2 = 0.01, and /physics exposes nu2
    # as an editable field.
    # Ma et al. Eq. (13) is the validity condition for the Eq. (18) bound:
    #
    #     0 <= nu2 < nu1     and     nu1 + nu2 < mu
    #
    # Testing `denom <= 0` is NOT equivalent. denom factorises as
    # (nu1 - nu2) * (mu - nu1 - nu2), so it is also POSITIVE when BOTH factors
    # are negative -- i.e. when both halves of Eq. (13) are violated at once.
    # Reachable through the editable nu2 field on /physics: mu = 0.5,
    # nu1 = 0.1, nu2 = 0.45 gives denom = +0.0175, sails past the old guard,
    # and returns 1.4912e-02 against a legitimate 1.2334e-02 -- a 21 %
    # overestimate with no theorem behind it, displayed as a secret-key rate.
    if not (0.0 <= nu2 < nu1 and nu1 + nu2 < mu):
        return 0.0
    denom = mu * nu1 - mu * nu2 - nu1 * nu1 + nu2 * nu2
    if denom <= 0:      # unreachable given Eq. (13) above; kept as a divisor guard
        return 0.0
    Y1_L = (mu / denom) * (
        Q_nu1 * math.exp(nu1) - Q_nu2 * math.exp(nu2)
        - (nu1 * nu1 - nu2 * nu2) / (mu * mu) * (Q_mu * math.exp(mu) - Y0)
    )
    Y1_L = max(Y1_L, 0.0)
    if Y1_L <= 0 or nu1 <= 0:
        return 0.0
    # Ma et al. Eq. (22), the GENERAL two-decoy bound:
    #
    #     e1 <= (E_nu1 Q_nu1 e^nu1 - E_nu2 Q_nu2 e^nu2) / ((nu1 - nu2) Y1^L)
    #
    # This previously used the Vacuum+Weak form -- Eq. (33), which substitutes
    # nu2 = 0 and e0 = 1/2 -- while Y1_L above had already been corrected to
    # the general nu2 form. So the two halves of the same rate assumed
    # different nu2, the mirror image of the defect fixed on the denominator.
    # It errs OPTIMISTIC: at the optimiser's own grid point nu2 = 0.01 the rate
    # came out +0.15 % high, and +0.70 % at nu2 = 0.05.
    #
    # At nu2 = 0 the two forms coincide exactly (E_nu2 Q_nu2 -> e0*Y0 = Y0/2),
    # so the shipped default and the golden vector are unaffected.
    if nu2 > 0:
        E_nu2 = qber_Emu(Y0, eta_total, e_d, nu2)
        e1_num = E_nu1 * Q_nu1 * math.exp(nu1) - E_nu2 * Q_nu2 * math.exp(nu2)
        e1_U = e1_num / ((nu1 - nu2) * Y1_L)
    else:
        e1_U = (E_nu1 * Q_nu1 * math.exp(nu1) - 0.5 * Y0) / (Y1_L * nu1)
    e1_U = max(0.0, min(0.5, e1_U))
    Q1 = mu * math.exp(-mu) * Y1_L
    rate = 0.5 * (-Q_mu * f_EC * H2(E_mu) + Q1 * (1.0 - H2(e1_U)))
    return max(rate, 0.0)


# ===========================================================================
# Finite-key analysis: Lim, Curty, Walenta, Xu, Zbinden,
# "Concise security bounds for practical decoy-state quantum key distribution",
# PRA 89, 022307 (2014), arXiv:1311.7129. Main text Eqs. (1)-(5), supplementary
# Eqs. (1)-(14).
#
# WHAT THIS REPLACED, and why it had to go
# -----------------------------------------
# The previous implementation was one line:
#
#     def finite_key_penalty(N, eps):
#         return math.sqrt(2.0 / N) * math.sqrt(math.log2(2.0 / eps))
#
# subtracted from the asymptotic per-pulse rate. Four independent faults:
#
#  1. MIS-CITED. Credited to arXiv:2511.21253 (Mizutani, Kawakami, Kato,
#     Quantum Sci. Technol. 11, 015010), which contains no such term -- it uses
#     Kato's inequality with explicit union bounds and models a PASSIVE
#     receiver, which is not this channel.
#  2. WRONG CONSTANT. sqrt(2/N)*sqrt(log2(2/eps)) is 2x the two-sided Hoeffding
#     deviation with log2 substituted for ln: 2.402x too large. Hoeffding
#     inversion never produces a base-2 log.
#  3. WRONG VARIABLE, WRONG PLACE. N is pulses SENT. The statistics live in the
#     DETECTION counts -- at 100 km, Q_mu = 1e-3, so n ~ 5e5 against N = 1e9.
#     And being channel-independent it never entered the decoy inversion, where
#     near-cancelling differences over small denominators amplify the deviation
#     by one to two orders of magnitude. That amplification is the DOMINANT
#     finite-size effect in decoy BB84 and was entirely absent.
#  4. NOT A BOUND IN EITHER DIRECTION. Optimistic on the statistics, pessimistic
#     on the rate, so it could not be defended as conservative. It zeroed the
#     key at 93 km where Lim et al. extract key past 135 km with n_X = 1e4.
#
# The tell: sqrt(2/N) gives a straight ~25 km per decade of N with NO
# saturation, so at N = 1e30 it claims key past 500 km -- beyond the distance
# where the asymptotic GLLP rate is identically zero. The correct curve
# asymptotes to that wall and never crosses it. See
# tests/test_finite_key_is_lim_2014.py, which pins exactly that.
#
# CONVENTIONS THAT ARE EASY TO GET WRONG
# ---------------------------------------
# * `delta` uses NATURAL log; `gamma` has ln2 in the denominator and log2
#   inside. Mixing them is a silent few-percent error.
# * In Eq. (3) `s_0` enters with a net PLUS sign, so the LOWER bound from
#   Eq. (2) must be substituted. The 1-decoy protocol (Rusca et al. 2018
#   Eq. (4)) needs the UPPER bound; using that convention here inflates the key
#   and nothing fails loudly.
# * The deviation term uses the TOTAL n_X, identically for every intensity k --
#   Lim states this explicitly -- and is then divided by p_k. For a rare
#   intensity that delta/p_k amplification dominates everything.
# * eps_sec = 21 * eps. The 21 and the 6 in `6*log2(21/eps_sec)` are one pair;
#   Rusca's 1-decoy form uses 19, Wiesemann's uses 15 or 17. Mixing a divisor
#   from one paper with a constant from another is unsound.
# ===========================================================================

#: Lim supp. Eq. (14) with every epsilon set equal: eps_sec = 21 * eps.
LIM_EPS_DIVISOR = 21.0
#: Coefficient of log2(LIM_EPS_DIVISOR / eps_sec) in Eq. (1).
LIM_UNION_COEFF = 6.0


def hoeffding_delta(n: float, eps: float) -> float:
    """Lim supp. Eq. (1): delta(n, eps) = sqrt((n/2) ln(1/eps)).

    NATURAL log. This is the inversion of P[|S - E S| >= t] <= 2 exp(-2t^2/n).
    """
    if n <= 0.0 or not 0.0 < eps < 1.0:
        return 0.0
    return math.sqrt(0.5 * n * math.log(1.0 / eps))


def photon_number_tau(n: int, mus: Sequence[float], ps: Sequence[float]) -> float:
    """Lim supp. Eq. (3): tau_n = sum_k p_k e^-k k^n / n!.

    The probability Alice emits an n-photon state, averaged over her intensity
    choice. Depends on the intensity PROBABILITIES, which is why they cannot be
    left implicit.
    """
    return sum(p * math.exp(-k) * k ** n
               for k, p in zip(mus, ps, strict=True)) / math.factorial(n)


def sampling_gamma(eps_sec: float, b: float, c: float, d: float) -> float:
    """Lim Eq. (5) gamma -- random sampling WITHOUT replacement.

    Fung, Ma, Chau, PRA 81, 012318 (2010). This is the term the old penalty had
    no analogue of at all.

        gamma(a,b,c,d) = sqrt( (c+d)(1-b)b / (c d ln2)
                               * log2( (c+d)/(c d (1-b) b) * 21^2/a^2 ) )

    The 21^2 is present because this is the MAIN-TEXT form, which takes
    a = eps_sec directly; the supplementary form takes alpha_1 = eps_sec/21 and
    omits it. Passing eps_sec/21 here as well would double-count the divisor.
    """
    if c <= 0.0 or d <= 0.0 or not 0.0 < b < 1.0:
        return 0.5
    pre = (c + d) * (1.0 - b) * b / (c * d * math.log(2.0))
    arg = (c + d) / (c * d * (1.0 - b) * b) * (LIM_EPS_DIVISOR / eps_sec) ** 2
    if arg <= 1.0:
        return 0.0
    return math.sqrt(pre * math.log2(arg))


def _bracketed(n_k: float, n_tot: float, k: float, p_k: float,
               dev: float) -> tuple[float, float]:
    """(n^+_k, n^-_k), Lim main text immediately below Eq. (2).

        n^{+/-}_k = (e^k / p_k) * clip(0, n_tot, n_k +/- delta(n_tot, eps))

    The clip to [0, n_tot] is sound because the true count lies there, and it
    is what the published reference implementations do.
    """
    scale = math.exp(k) / p_k
    return (scale * min(max(n_k + dev, 0.0), n_tot),
            scale * min(max(n_k - dev, 0.0), n_tot))


def _s0_s1(n_k: Sequence[float], mus: Sequence[float], ps: Sequence[float],
           eps: float, tau0: float, tau1: float) -> tuple[float, float, float]:
    """Lim Eqs. (2) and (3) for ONE basis. Returns (s_0, s_1, n_total)."""
    mu1, mu2, mu3 = mus
    n_tot = sum(n_k)
    dev = hoeffding_delta(n_tot, eps)          # the TOTAL, for every k alike
    n1p, _ = _bracketed(n_k[0], n_tot, mu1, ps[0], dev)
    n2p, n2m = _bracketed(n_k[1], n_tot, mu2, ps[1], dev)
    n3p, n3m = _bracketed(n_k[2], n_tot, mu3, ps[2], dev)

    # Eq. (2): vacuum events, LOWER bound.
    s0 = tau0 * (mu2 * n3m - mu3 * n2p) / (mu2 - mu3)
    s0 = min(max(s0, 0.0), n_tot)

    # Eq. (3): single-photon events, LOWER bound. s0 enters with a net PLUS
    # sign, so the lower bound above is the correct substitution -- see the
    # sign trap noted at the top of this section.
    den = mu1 * (mu2 - mu3) - mu2 ** 2 + mu3 ** 2
    if den <= 0.0:
        return s0, 0.0, n_tot
    s1 = (tau1 * mu1 * (n2m - n3p
                        - (mu2 ** 2 - mu3 ** 2) / mu1 ** 2 * (n1p - s0 / tau0))) / den
    return s0, min(max(s1, 0.0), n_tot), n_tot


def _v1(m_k: Sequence[float], mus: Sequence[float], ps: Sequence[float],
        eps: float, tau1: float) -> float:
    """Lim Eq. (4): single-photon BIT errors in Z, upper bound."""
    _, mu2, mu3 = mus
    m_tot = sum(m_k)
    dev = hoeffding_delta(m_tot, eps)
    m2p, _ = _bracketed(m_k[1], m_tot, mu2, ps[1], dev)
    _, m3m = _bracketed(m_k[2], m_tot, mu3, ps[2], dev)
    return max(0.0, tau1 * (m2p - m3m) / (mu2 - mu3))


def lim_key_length(*, nX_k: Sequence[float], nZ_k: Sequence[float],
                   mX_k: Sequence[float], mZ_k: Sequence[float],
                   mus: Sequence[float], ps: Sequence[float],
                   eps_sec: float, eps_cor: float, f_EC: float) -> dict:
    """Lim Eq. (1): the secret key LENGTH in bits, plus every intermediate.

    A LENGTH, not a rate. The old code subtracted a constant from a per-pulse
    rate, which no theorem licenses -- the rate is not an empirical mean of N
    bounded i.i.d. variables. Divide by the pulses sent to get a rate.

    Returns the diagnostics as well as `ell` because every one of them is a
    place this can go quietly wrong, and a caller that can only see the final
    scalar cannot tell a sign error from a channel that is genuinely too lossy.
    """
    eps = eps_sec / LIM_EPS_DIVISOR
    tau0 = photon_number_tau(0, mus, ps)
    tau1 = photon_number_tau(1, mus, ps)

    sX0, sX1, nX = _s0_s1(nX_k, mus, ps, eps, tau0, tau1)
    sZ0, sZ1, nZ = _s0_s1(nZ_k, mus, ps, eps, tau0, tau1)
    vZ1 = min(_v1(mZ_k, mus, ps, eps, tau1), sZ1)

    mX = sum(mX_k)
    leak_ec = nX * f_EC * H2(mX / nX) if nX > 0 else 0.0

    if sZ1 <= 0.0 or sX1 <= 0.0:
        phiX = 0.5
    else:
        b = vZ1 / sZ1
        phiX = min(0.5, b + sampling_gamma(eps_sec, b, sZ1, sX1))

    penalty = (LIM_UNION_COEFF * math.log2(LIM_EPS_DIVISOR / eps_sec)
               + math.log2(2.0 / eps_cor))
    ell_raw = sX0 + sX1 * (1.0 - H2(phiX)) - leak_ec - penalty
    return {
        "ell": max(0.0, ell_raw), "ell_raw": ell_raw,
        "n_X": nX, "n_Z": nZ, "m_X": mX, "m_Z": sum(mZ_k),
        "s_X0": sX0, "s_X1": sX1, "s_Z0": sZ0, "s_Z1": sZ1,
        "v_Z1": vZ1, "phi_X": phiX, "leak_EC": leak_ec,
        "tau_0": tau0, "tau_1": tau1, "eps_penalty_bits": penalty,
    }


def lim_counts_from_channel(*, N: float, qx: float, mus: Sequence[float],
                            ps: Sequence[float], Y0: float, eta_total: float,
                            e_d: float) -> dict:
    """Bridge the analytic channel model to the per-intensity counts Lim needs.

    IMPORTANT, and it must not be buried: these are EXPECTED counts, not
    observed ones. Lim's theorem is conditioned on the data of one run -- given
    the observed (n_{X,k}, m_{Z,k}), a key of length `ell` is eps_sec-secret.
    Substituting expectations yields ell(E[data]), which is neither E[ell] nor a
    bound on `ell` for any particular run; a real run lands below it about half
    the time.

    This IS the standard simulation convention -- Lim's own Fig. 1, Rusca's
    Fig. 1 and Wiesemann's Fig. 5 all do exactly this -- so it is defensible.
    But the output is an EXPECTED key length under a modelled channel, never an
    achieved one, and the eps_sec guarantee does not attach to it.

    Also note Hoeffding assumes independent trials. `dead_time_s` and
    `after_pulse_prob` in the shipped config correlate consecutive trials and
    this channel model ignores both; if a discrete-event backend ever supplies
    real counts, that assumption needs revisiting.
    """
    Q = [gain_Qmu(Y0, eta_total, k) for k in mus]
    E = [qber_Emu(Y0, eta_total, e_d, k) for k in mus]
    nX = [N * qx ** 2 * p * q for p, q in zip(ps, Q, strict=True)]
    nZ = [N * (1.0 - qx) ** 2 * p * q for p, q in zip(ps, Q, strict=True)]
    return {
        "nX_k": nX, "nZ_k": nZ,
        "mX_k": [n * e for n, e in zip(nX, E, strict=True)],
        "mZ_k": [n * e for n, e in zip(nZ, E, strict=True)],
        "Q_k": Q, "E_k": E,
    }


def skr_finite(*, Y0, eta_total, e_d, mu, nu1, nu2, f_EC, N, eps,
               qx: float = 0.5, p_mu: float = 0.70, p_nu1: float = 0.15,
               p_nu2: float = 0.15, eps_cor: float = 1.0e-15) -> float:
    """Finite-key secret-key rate per pulse SENT, via Lim et al. Eq. (1).

    `eps` is eps_sec. `N` is pulses SENT -- it appears in no bound, only in the
    final division; the statistics are driven by the detection counts.

    The intensity probabilities have defaults so existing callers keep working,
    but they are real physics: tau_1 depends on them, and so does the delta/p_k
    amplification that dominates the finite-size cost. Pass them from config.
    """
    if N <= 0 or not 0.0 < eps < 1.0:
        return 0.0
    mus, ps = (mu, nu1, nu2), (p_mu, p_nu1, p_nu2)
    if not (mu > nu1 + nu2 and nu1 > nu2 >= 0.0):
        return 0.0            # Lim's ordering, the analogue of Ma Eq. (13)
    counts = lim_counts_from_channel(N=N, qx=qx, mus=mus, ps=ps, Y0=Y0,
                                     eta_total=eta_total, e_d=e_d)
    res = lim_key_length(nX_k=counts["nX_k"], nZ_k=counts["nZ_k"],
                         mX_k=counts["mX_k"], mZ_k=counts["mZ_k"],
                         mus=mus, ps=ps, eps_sec=eps, eps_cor=eps_cor,
                         f_EC=f_EC)
    return res["ell"] / N


def drop_rate_for_simulator(*, Y0: float, eta_total: float, mu: float) -> float:
    """1 - Q_μ — usable directly as photonic loss probability for SimQN/SeQUeNCe."""
    return max(0.0, min(1.0, 1.0 - gain_Qmu(Y0, eta_total, mu)))


def skr_bps_from_config(cfg) -> float:
    """Secret-key rate in bits/second for a BackendConfig.

    Every backend previously derived `skr_bps` its own way, and none of them
    computed a secret-key rate:

        qutip            n_sifted / n_photons * pulse_rate     (sifting fraction)
        simqn            sifted / batch_size * pulse_rate      (sifting fraction)
        qkdnetsim_proxy  pulse_rate / 2                        (a constant)

    A sifting fraction is the proportion of pulses that survive basis
    reconciliation. The secret-key rate is what remains after error correction
    leaks f_EC * h2(E_mu) and privacy amplification removes Eve's information --
    always strictly smaller, and on the default configuration smaller by a
    factor of about 41. Reporting the former in a field named `skr_bps`
    overstates the project's headline result.

    This routes all three through the GLLP/Lo-Ma decoy-state model already in
    this module, which tests/test_keyrate_golden_vector.py pins to the
    published worked example (Ma et al. 2005, GYS parameters,
    R = 2.555e-3 bits/pulse). One implementation, one test.
    """
    eta = total_transmittance(
        cfg.detector_efficiency, cfg.fiber_attenuation_db_per_km, cfg.link_length_km,
    )
    Y0 = cfg.dark_count_rate_hz / max(cfg.pulse_rate_hz, 1.0)
    r_per_pulse = skr_finite(
        Y0=Y0, eta_total=eta, e_d=cfg.misalignment_error_ed,
        mu=cfg.intensity_signal_mu, nu1=cfg.intensity_decoy_1_nu1,
        nu2=cfg.intensity_decoy_2_nu2, f_EC=cfg.ec_efficiency_f,
        N=cfg.block_size_N, eps=cfg.security_epsilon,
        # Passed explicitly rather than left on the defaults: tau_n depends on
        # the intensity probabilities and the Hoeffding deviation is divided by
        # them, so defaults that silently disagree with the YAML would give a
        # rate for a protocol nobody is running.
        qx=cfg.basis_bias_pz,
        p_mu=cfg.prob_signal_mu, p_nu1=cfg.prob_decoy_1_nu1,
        p_nu2=cfg.prob_decoy_2_nu2,
        eps_cor=cfg.correctness_epsilon,
    )
    return r_per_pulse * cfg.pulse_rate_hz


def accepts_round(qber: float, skr_bps: float, cfg) -> bool:
    """Should a round that produced bits be handed out as a secret key?

    Two conditions, not one. `qber < cfg.qber_threshold_abort` alone is not
    sufficient, and the gap between the two is a real band of distances.

    **`qber_threshold_abort` is 0.11, and 0.11 is the wrong number to stop at.**
    It is the Shor-Preskill bound -- the root of `1 - 2*h2(e) = 0`, computed
    independently here as **11.003 %** -- which holds for *ideal single photons
    with perfect error correction*. What this repository actually models is a
    decoy-state weak-coherent-pulse source with `f_EC = 1.16`, whose GLLP rate

        R = q * { -Q_mu * f_EC * h2(E_mu) + Q_1 * [1 - h2(e_1)] }

    reaches zero much earlier.

    **`skr_bps` here is the FINITE-KEY rate, not the asymptotic one.** Callers
    pass `skr_bps_from_config`, which calls `skr_finite`, so this predicate
    crosses zero 160 km before the asymptotic GLLP curve that `/physics` and
    `/verify` display. An earlier revision of this docstring quoted the
    asymptotic band, and the test that was supposed to pin it called
    `asymptotic_skr_per_pulse` directly -- so it passed while describing a band
    production never reaches. Measured on the shipped config (mu = 0.5,
    e_d = 0.015, f_EC = 1.16, N = 1e9, eps = 1e-10)::

         L(km)     QBER    R_asym     R_finite   old pred   this pred
            90  0.01503  3.04e-04   4.28e-05    accept     accept
            93  0.01504  2.65e-04   3.44e-06    accept     accept
          93.3  0.01504  2.61e-04   0.000000    accept     REJECT   <-- here
           150  0.01548  1.90e-05   0.000000    accept     REJECT
           253  0.06495  3.29e-09   0.000000    accept     REJECT
           254  0.06705  0.000000   0.000000    accept     REJECT
           270  0.11237  0.000000   0.000000    abort      REJECT

    The band where the old QBER-only test accepted a zero-rate round is
    **93.3 km to 270 km at QBER 1.504 % to 11.0 %**, not the 254-270 km the
    earlier text claimed. The conclusion is unchanged and in fact stronger --
    the QBER test alone admits a far wider dead band than first measured.

    Note the two curves disagree by 160 km, which is itself worth knowing: the
    rate the product SHOWS is not the rate it ACCEPTS on. See the finite-key
    caveat on `skr_finite`. `simqn` -- the default backend -- returned a
    256-bit key there, `/verify` displayed `skr_bps: 0`, and both were reported
    as a healthy round. A key extracted at a rate the project's own model puts
    at zero carries no proven secrecy: privacy amplification has no entropy to
    draw on, so the output is a hash of bits Eve may hold entirely.

    `tno_backend.py` already had this right (`res["rate_per_pulse"] > 0.0 and
    qber < threshold`). This lifts that predicate to where the other two
    backends can share it rather than each re-deciding.

    Note `skr_bps` is a *modelled* rate from the configured physics, not a
    measurement of this round. That is the same quantity the UI displays, which
    is the point: the accept decision and the displayed rate can no longer
    disagree.
    """
    return skr_bps > 0.0 and qber < cfg.qber_threshold_abort
