"""Shared closed-form SKR helpers (Lo-Ma 2005 + arXiv:2511.21253).

Used by every backend that needs a science-grounded channel model, OR a
secret-key-rate sanity check, without invoking heavy simulators.
"""
from __future__ import annotations

import math


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
    denom = mu * nu1 - mu * nu2 - nu1 * nu1 + nu2 * nu2
    if denom <= 0:
        return 0.0
    Y1_L = (mu / denom) * (
        Q_nu1 * math.exp(nu1) - Q_nu2 * math.exp(nu2)
        - (nu1 * nu1 - nu2 * nu2) / (mu * mu) * (Q_mu * math.exp(mu) - Y0)
    )
    Y1_L = max(Y1_L, 0.0)
    if Y1_L <= 0 or nu1 <= 0:
        return 0.0
    e1_U = (E_nu1 * Q_nu1 * math.exp(nu1) - 0.5 * Y0) / (Y1_L * nu1)
    e1_U = max(0.0, min(0.5, e1_U))
    Q1 = mu * math.exp(-mu) * Y1_L
    rate = 0.5 * (-Q_mu * f_EC * H2(E_mu) + Q1 * (1.0 - H2(e1_U)))
    return max(rate, 0.0)


def finite_key_penalty(N: int, eps: float) -> float:
    """arXiv:2511.21253 first-order finite-size correction term."""
    if N <= 0 or eps <= 0:
        return 0.0
    return math.sqrt(2.0 / N) * math.sqrt(math.log2(2.0 / eps))


def skr_finite(*, Y0, eta_total, e_d, mu, nu1, nu2, f_EC, N, eps) -> float:
    R = asymptotic_skr_per_pulse(
        Y0=Y0, eta_total=eta_total, e_d=e_d,
        mu=mu, nu1=nu1, nu2=nu2, f_EC=f_EC,
    )
    return max(R - finite_key_penalty(N, eps), 0.0)


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
