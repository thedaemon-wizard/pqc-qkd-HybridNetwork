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
    denom = mu * nu1 - nu1 * nu1
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
