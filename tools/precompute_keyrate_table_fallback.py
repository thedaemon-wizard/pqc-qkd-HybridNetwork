#!/usr/bin/env python3
"""Produce the SKR lookup table shipped as config/qkd_keyrate_table.json.

This script is that file's PRODUCER, not a fallback for one. The header here
used to read "This is the FOSS fallback for `tools/precompute_keyrate_table.m`
(which requires MATLAB + CVX + QETLAB). The output JSON is the SAME shape so
the runtime never knows the provenance." Seven documents took that framing
literally and credited the shipped table to an openQKDsecurity Winick SDP.

No `.m` file of that name has ever existed in this repository -- checked
against the whole history, not just HEAD -- nothing anywhere invokes
openQKDsecurity, and the table's own `provenance` field names this script. The
"fallback" framing is what made the misattribution look plausible, so it is
gone. "The runtime never knows the provenance" is also exactly the property
that let the error survive: nothing downstream could contradict it.

The `_fallback` suffix stays for now because docs/keyrate.md, docs/phases.md
and the committed JSON all reference this path; renaming is its own change.

Implements the closed-form finite-key secret-key rate for decoy-state BB84
WCP per the formulas in:

  [1] H.-K. Lo, X. Ma, K. Chen, "Decoy state quantum key distribution",
      Phys. Rev. Lett. 94, 230504 (2005). DOI 10.1103/PhysRevLett.94.230504
  [2] Lim, Curty, Walenta, Xu, Zbinden, PRA 89, 022307 (2014), arXiv:1311.7129,
      "Concise security bounds for practical decoy-state QKD" -- the finite-key
      analysis, applied through services/bb84-kme/app/backends/_skr.py rather
      than reimplemented here. (Was arXiv:2511.21253, which does not contain
      the formula this tool used.)
  [3] M. Curty, F. Xu, et al., Nature Communications 5, 3732 (2014).

The output table is committed to git so the shipped configuration has
production-quality defaults without re-running this script; regenerate it
whenever the physical parameters change.

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
from pathlib import Path  # noqa: E402

# One implementation of the finite-key analysis, not two. This tool used to
# carry its own copy of the (wrong) sqrt(2/N) penalty and write the result into
# config/qkd_keyrate_table.json as shipped data, so a fix in the other copy
# would have left this one silently stale.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]
                       / "services" / "bb84-kme"))
from app.backends import _skr  # noqa: E402

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


def asymptotic_skr_per_pulse(p: PhysParams) -> float:
    """Asymptotic GLLP rate per pulse, delegated to the shipped implementation.

    This file used to carry its own `decoy_bounds()` and its own GLLP
    assembly -- a THIRD copy of the decoy model, alongside
    `services/bb84-kme/app/backends/_skr.py` and
    `services/webui-frontend/src/lib/sim/keyrate.ts`. It received half of the
    corrections the other two got, and the half it missed had a hard failure
    in it:

        def decoy_bounds(p) -> tuple[float, float]:
            ...
            if denom <= 0:
                return 0.0          # <-- a bare float from a tuple-annotated
                                    #     function, and the only caller does
                                    #     `Y1_L, e1_U = decoy_bounds(p)`

    Reproduced before removing it, with mu=0.5, nu1=0.3, nu2=0.25 -- which
    violates Ma et al. Eq. (15)'s `nu1 + nu2 < mu`, the very condition that
    branch exists to enforce:

        denom = -0.002500  ->  TypeError: cannot unpack non-iterable float

    Reachable from the browser: `source.intensity_decoy_2_nu2` is an editable
    field on /physics whose bound is `[0, null]`, so nu2 has no upper limit.

    `_skr` already carries the Eq. (15) validity guard (`_skr.py:67`) and the
    general Eq. (25) e1 that this copy never received. Delegating removes the
    third implementation rather than repairing it, which is what
    `finite_key_correction` below already does for the finite-key half -- and
    for the reason its docstring gives: a duplicate is how the original defect
    survived a fix in the other copy.
    """
    return _skr.asymptotic_skr_per_pulse(
        Y0=p.Y0, eta_total=channel_transmittance(p), e_d=p.e_d,
        mu=p.mu, nu1=p.nu1, nu2=p.nu2, f_EC=p.f_EC,
    )


def finite_key_correction(p: PhysParams, N: int, eps: float = 1e-10,
                          eps_cor: float = 1e-15) -> float:
    """Finite-key rate per pulse, delegated to the shipped implementation.

    This used to carry its OWN copy of

        R_N ~ R_inf - sqrt(2/N) * sqrt(log2(2/eps))

    credited to arXiv:2511.21253, which contains no such term. Two copies of
    the same wrong formula, and this one wrote its output into
    `config/qkd_keyrate_table.json` as `R_finite_per_pulse` -- shipped data.

    It now calls `services/bb84-kme/app/backends/_skr.py`, so there is one
    implementation of Lim et al. (PRA 89, 022307 (2014), arXiv:1311.7129) and
    the table cannot drift from the runtime model. A duplicate is how the
    original defect survived a fix in the other copy.
    """
    if N <= 0:
        return 0.0
    return _skr.skr_finite(
        Y0=p.Y0, eta_total=channel_transmittance(p), e_d=p.e_d,
        mu=p.mu, nu1=p.nu1, nu2=p.nu2, f_EC=p.f_EC,
        N=N, eps=eps, eps_cor=eps_cor,
        qx=0.5, p_mu=0.70, p_nu1=0.15, p_nu2=0.15,
    )


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
        p_opt = PhysParams(distance_km=distance, eta_d=eta_d, Y0=Y0, e_d=e_d, mu=mu_opt)
        # The finite rate is computed at the OPTIMISED mu, matching R_inf.
        # Passing the un-optimised `p` would have paired an asymptotic rate at
        # mu_opt with a finite rate at the default mu in the same table row.
        R_N = finite_key_correction(p_opt, N_block)
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
            "Lim et al. PRA 89, 022307 (2014) finite-key (via app/backends/_skr.py)",
        ],
        "block_size_N": args.N,
        "rows": rows,
    }, indent=1))
    log.info("wrote %d rows to %s", len(rows), out_path)


if __name__ == "__main__":
    main()
