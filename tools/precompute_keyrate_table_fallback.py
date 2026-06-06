#!/usr/bin/env python3
"""Precompute scientifically-grounded SKR lookup table without MATLAB.

This is the FOSS fallback for `tools/precompute_keyrate_table.m` (which
requires MATLAB + CVX + QETLAB).  The output JSON is the SAME shape so the
runtime never knows the provenance.

Implements the closed-form finite-key secret-key rate for decoy-state BB84
WCP per the formulas in:

  [1] H.-K. Lo, X. Ma, K. Chen, "Decoy state quantum key distribution",
      Phys. Rev. Lett. 94, 230504 (2005). DOI 10.1103/PhysRevLett.94.230504
  [2] arXiv:2511.21253 (2026), "Finite-key security analysis of the decoy-state
      BB84 QKD with passive measurement" — closed-form finite-key bound.
  [3] M. Curty, F. Xu, et al., Nature Communications 5, 3732 (2014).

The output table is committed to git so users without MATLAB still have
production-quality defaults.

Usage:
    python tools/precompute_keyrate_table_fallback.py --out config/qkd_keyrate_table.json
"""
from __future__ import annotations

import argparse
import itertools
import json
import logging
import math
import os
import sys
from dataclasses import dataclass
from logging.handlers import RotatingFileHandler


def _setup_logger() -> logging.Logger:
    from pathlib import Path
    log_dir = Path(os.environ.get("LOG_DIR", "benchmarks/results"))
    log_dir.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s %(message)s")
    root = logging.getLogger(); root.setLevel(logging.INFO); root.handlers.clear()
    sh = logging.StreamHandler(); sh.setFormatter(fmt); root.addHandler(sh)
    fh = RotatingFileHandler(log_dir / "precompute_keyrate_table.log",
                              maxBytes=5_000_000, backupCount=3, encoding="utf-8")
    fh.setFormatter(fmt); root.addHandler(fh)
    return logging.getLogger("precompute-keyrate")


log = _setup_logger()
from pathlib import Path

H2 = lambda x: -x * math.log2(x) - (1 - x) * math.log2(1 - x) if 0 < x < 1 else 0.0


@dataclass(frozen=True, slots=True)
class PhysParams:
    distance_km: float
    eta_d: float                 # detector efficiency
    Y0: float                    # dark count probability per gate
    e_d: float = 0.015           # misalignment
    alpha_db_per_km: float = 0.2
    mu: float = 0.5
    nu1: float = 0.1
    nu2: float = 0.0
    f_EC: float = 1.16


def channel_transmittance(p: PhysParams) -> float:
    """Total transmittance = fiber × detector."""
    return p.eta_d * 10 ** (-p.alpha_db_per_km * p.distance_km / 10)


def gain(p: PhysParams, intensity: float) -> float:
    """Q_mu = Y0 + 1 - exp(-eta_total · mu)  (Lo-Ma 2005 eq. 32)."""
    eta = channel_transmittance(p)
    return p.Y0 + 1 - math.exp(-eta * intensity)


def qber(p: PhysParams, intensity: float) -> float:
    """E_mu = [Y0/2 + e_d · (1 - exp(-eta · mu))] / Q_mu  (Lo-Ma 2005 eq. 33)."""
    eta = channel_transmittance(p)
    q = gain(p, intensity)
    if q <= 0:
        return 0.5
    return (p.Y0 / 2 + p.e_d * (1 - math.exp(-eta * intensity))) / q


def decoy_bounds(p: PhysParams) -> tuple[float, float]:
    """Lower bound on Y1 (single-photon yield) and upper bound on e1 (s-photon QBER).

    Two-decoy Lo-Ma analytical bounds (PRL 94 230504 eqs. 34-35):
       Y1_L = (mu / (mu*nu1 - nu1^2)) * (Q_nu1 * exp(nu1) - Q_nu2 * exp(nu2)
              - (nu1^2 - nu2^2)/mu^2 * (Q_mu * exp(mu) - Y0) )
       e1_U = (E_nu1 * Q_nu1 * exp(nu1) - 0.5 * Y0) / (Y1_L * nu1)
    """
    Q_mu = gain(p, p.mu)
    Q_nu1 = gain(p, p.nu1)
    Q_nu2 = gain(p, p.nu2) if p.nu2 > 0 else p.Y0
    E_nu1 = qber(p, p.nu1)

    if p.nu1 <= 0 or p.mu - p.nu1 <= 0:
        return 0.0, 0.5

    denom = p.mu * p.nu1 - p.nu1 * p.nu1
    Y1_L = (p.mu / denom) * (
        Q_nu1 * math.exp(p.nu1) - Q_nu2 * math.exp(p.nu2)
        - (p.nu1 ** 2 - p.nu2 ** 2) / (p.mu ** 2)
          * (Q_mu * math.exp(p.mu) - p.Y0)
    )
    Y1_L = max(Y1_L, 0.0)

    if Y1_L <= 0 or p.nu1 <= 0:
        return 0.0, 0.5
    e1_U = (E_nu1 * Q_nu1 * math.exp(p.nu1) - 0.5 * p.Y0) / (Y1_L * p.nu1)
    e1_U = max(0.0, min(0.5, e1_U))
    return Y1_L, e1_U


def asymptotic_skr_per_pulse(p: PhysParams) -> float:
    """GLLP rate: R ≥ q { -Q_mu · f · H2(E_mu) + Q1 · [1 - H2(e1)] }
    with Q1 = mu · exp(-mu) · Y1_L  and q ≈ 1/2 (basis symmetrisation)."""
    Q_mu = gain(p, p.mu)
    E_mu = qber(p, p.mu)
    Y1_L, e1_U = decoy_bounds(p)
    Q1 = p.mu * math.exp(-p.mu) * Y1_L
    rate = 0.5 * (-Q_mu * p.f_EC * H2(E_mu) + Q1 * (1 - H2(e1_U)))
    return max(rate, 0.0)


def finite_key_correction(R_inf: float, N: int, eps: float = 1e-10) -> float:
    """First-order finite-key penalty per arXiv 2511.21253 closed-form:
        R_N ≈ R_inf - sqrt(2 / N) * sqrt(log2(2 / eps))
    """
    if N <= 0 or R_inf <= 0:
        return 0.0
    penalty = math.sqrt(2.0 / N) * math.sqrt(math.log2(2.0 / eps))
    return max(R_inf - penalty, 0.0)


def precompute(distances_km, etas, y0s, eds, N_block) -> list[dict]:
    rows: list[dict] = []
    for distance, eta_d, Y0, e_d in itertools.product(distances_km, etas, y0s, eds):
        p = PhysParams(distance_km=distance, eta_d=eta_d, Y0=Y0, e_d=e_d)
        # Greedy μ optimisation over a coarse 1-D grid (BO handled at runtime)
        best = (0.0, p.mu)
        for mu in [0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8]:
            q = PhysParams(distance_km=distance, eta_d=eta_d, Y0=Y0, e_d=e_d, mu=mu)
            r = asymptotic_skr_per_pulse(q)
            if r > best[0]:
                best = (r, mu)
        R_inf = best[0]
        mu_opt = best[1]
        R_N = finite_key_correction(R_inf, N_block)
        p_opt = PhysParams(distance_km=distance, eta_d=eta_d, Y0=Y0, e_d=e_d, mu=mu_opt)
        rows.append({
            "distance_km": distance,
            "eta_d": eta_d,
            "Y0": Y0,
            "e_d": e_d,
            "mu_opt": mu_opt,
            "nu1": p_opt.nu1,
            "nu2": p_opt.nu2,
            "Q_mu": gain(p_opt, p_opt.mu),
            "E_mu": qber(p_opt, p_opt.mu),
            "R_asymptotic_per_pulse": R_inf,
            "R_finite_per_pulse": R_N,
        })
    return rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="config/qkd_keyrate_table.json")
    ap.add_argument("--N", type=int, default=10**9,
                    help="finite-key block size (default 1e9)")
    args = ap.parse_args()

    distances = list(range(0, 251, 10))          # 0..250 km step 10
    etas = [0.05, 0.10, 0.20, 0.30, 0.45]
    y0s = [1e-7, 1e-6, 1e-5]
    eds = [0.005, 0.015, 0.030]
    rows = precompute(distances, etas, y0s, eds, args.N)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps({
        "schema": "qkd_keyrate_table.v1",
        "provenance": "tools/precompute_keyrate_table_fallback.py",
        "formulas": [
            "Lo-Ma-Chen PRL 94, 230504 (2005)",
            "arXiv 2511.21253 (2026) closed-form finite-key bound",
        ],
        "block_size_N": args.N,
        "rows": rows,
    }, indent=1))
    log.info("wrote %d rows to %s", len(rows), out_path)


if __name__ == "__main__":
    main()
