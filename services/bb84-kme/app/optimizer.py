"""Bayesian-Optimization-driven WCP parameter selection.

Objective: finite-key SKR (Lo-Ma 2005 decoy bound + Lim et al. PRA 89, 022307 (2014), arXiv:1311.7129).
The finite-key half was previously credited to arXiv:2511.21253, which
contains no such formula; see services/bb84-kme/app/backends/_skr.py.
Method:    scikit-optimize gp_minimize (Gaussian Process + Expected Improvement).

Why BO?  Because the SKR is a smooth, non-convex function of (μ, ν1, ν2, pz),
and BO is sample-efficient when each evaluation is cheap-but-not-free. The
fallback `closed_form_only` simply scans μ on a coarse grid.

Used from POST /api/optimize (WebUI button) and from CI parameter sweeps.

References:
- Snoek, Larochelle, Adams "Practical Bayesian Optimization" NeurIPS 2012
- arXiv:2412.20265 (2024) Bayesian Optimisation for QKD intensity selection
- Lim et al. PRA 89, 022307 (2014), arXiv:1311.7129, finite-key key length (Eqs. 1-5)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from .backends._skr import skr_finite, total_transmittance

log = logging.getLogger(__name__)


@dataclass(slots=True)
class OptimizeResult:
    mu: float
    nu1: float
    nu2: float
    pz: float
    skr_per_pulse: float
    n_calls: int
    method: str
    history: list[dict[str, Any]]


def _objective(x: list[float], *, fixed: dict[str, float]) -> float:
    mu, nu1, nu2, _pz = x
    if mu <= nu1 or nu1 <= nu2:
        return 0.0
    R = skr_finite(
        Y0=fixed["Y0"], eta_total=fixed["eta_total"], e_d=fixed["e_d"],
        mu=mu, nu1=nu1, nu2=max(nu2, 0.0),
        f_EC=fixed["f_EC"], N=fixed["N"], eps=fixed["eps"],
    )
    # Deliberately NOT weighted by a basis-match probability.
    #
    # This used to return -R * (pz^2 + (1-pz)^2). But the sifting factor q is
    # already inside the rate model: `_skr.asymptotic_skr_per_pulse` opens with
    # `rate = 0.5 * (...)`, which is the q = 1/2 of symmetric BB84. Multiplying
    # by p_match applied sifting a second time, so every reported
    # `skr_per_pulse` was exactly half the true value at pz = 0.5.
    #
    # It also made the pz search dimension misleading rather than merely
    # useless: p_match climbs from 0.5 to ~0.905 as pz goes 0.5 -> 0.95, so the
    # objective rewarded asymmetric bases even though the underlying rate model
    # has no pz dependence at all. Optimising pz only becomes meaningful once q
    # is threaded through `_skr` as a parameter; until then pz is reported but
    # not optimised, and `_pz` is unused on purpose.
    return -R


def optimize_bayesian(
    *, eta_total: float, Y0: float, e_d: float, f_EC: float, N: int, eps: float,
    n_calls: int = 50, seed: int | None = None,
) -> OptimizeResult:
    """Run gp_minimize on the SKR objective.

    Falls back to the deterministic closed-form scan if scikit-optimize cannot
    be imported (lighter Docker images).
    """
    fixed = {"Y0": Y0, "eta_total": eta_total, "e_d": e_d,
             "f_EC": f_EC, "N": N, "eps": eps}
    history: list[dict[str, Any]] = []
    try:
        from skopt import gp_minimize
        from skopt.space import Real
    except Exception as e:
        log.warning("scikit-optimize unavailable, using closed-form fallback: %s", e)
        return optimize_closed_form(eta_total=eta_total, Y0=Y0, e_d=e_d,
                                     f_EC=f_EC, N=N, eps=eps)

    space = [
        Real(0.30, 0.90, name="mu"),
        Real(0.05, 0.20, name="nu1"),
        Real(0.00, 0.01, name="nu2"),
        Real(0.50, 0.95, name="pz"),
    ]

    def cb(x):
        val = _objective(list(x), fixed=fixed)
        history.append({"x": list(x), "obj": val})
        return val

    res = gp_minimize(
        cb, dimensions=space, acq_func="EI",
        n_calls=n_calls, n_initial_points=10,
        random_state=seed if seed is not None else 0,
        noise=1e-10,
    )
    mu, nu1, nu2, pz = res.x
    return OptimizeResult(
        mu=float(mu), nu1=float(nu1), nu2=float(nu2), pz=float(pz),
        skr_per_pulse=float(-res.fun),
        n_calls=n_calls,
        method="bayesian_gp",
        history=history,
    )


def optimize_closed_form(
    *, eta_total: float, Y0: float, e_d: float, f_EC: float, N: int, eps: float,
) -> OptimizeResult:
    """Deterministic μ scan; ν1=μ/5, ν2=0; pz=0.5 (symmetric BB84)."""
    fixed = {"Y0": Y0, "eta_total": eta_total, "e_d": e_d,
             "f_EC": f_EC, "N": N, "eps": eps}
    history: list[dict[str, Any]] = []
    best = (0.0, 0.5, 0.1, 0.0, 0.5)
    step = 0.05
    mu = 0.30
    while mu <= 0.901:
        nu1 = mu / 5.0
        x = [mu, nu1, 0.0, 0.5]
        val = -_objective(x, fixed=fixed)   # positive SKR
        history.append({"x": x, "obj": -val})
        if val > best[0]:
            best = (val, mu, nu1, 0.0, 0.5)
        mu += step
    skr, mu, nu1, nu2, pz = best
    return OptimizeResult(
        mu=mu, nu1=nu1, nu2=nu2, pz=pz,
        skr_per_pulse=skr,
        n_calls=len(history),
        method="closed_form",
        history=history,
    )


def optimize_from_yaml() -> OptimizeResult:
    """Convenience: load central config and run."""
    from . import config_loader as cl
    eta_total = total_transmittance(
        float(cl.get("physical.detector_efficiency")),
        float(cl.get("physical.fiber_attenuation_db_per_km")),
        float(cl.get("physical.link_length_km")),
    )
    Y0 = float(cl.get("physical.dark_count_rate_hz")) / max(
        float(cl.get("source.pulse_rate_hz")), 1.0,
    )
    e_d = float(cl.get("physical.misalignment_error_ed"))
    f_EC = float(cl.get("protocol.ec_efficiency_f"))
    N = int(float(cl.get("protocol.block_size_N")))
    eps = float(cl.get("protocol.security_epsilon"))
    method = cl.get("optimizer.method", "bayesian_gp")
    n_calls = int(cl.get("optimizer.n_calls", 50))
    if method == "closed_form":
        return optimize_closed_form(eta_total=eta_total, Y0=Y0, e_d=e_d,
                                     f_EC=f_EC, N=N, eps=eps)
    return optimize_bayesian(eta_total=eta_total, Y0=Y0, e_d=e_d,
                              f_EC=f_EC, N=N, eps=eps, n_calls=n_calls)
