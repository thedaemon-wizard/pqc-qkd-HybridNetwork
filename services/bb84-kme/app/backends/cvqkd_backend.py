"""CV-QKD backend — GG02 protocol on Strawberry Fields.

Adds **continuous-variable** modality (Grosshans-Grangier 2002, PRL 88 057902)
to address the §12 limitation about discrete-variable-only physics.

Note (2026-01): Xanadu announced cloud-hardware decommissioning. The real-
hardware backend (`X8`/`Borealis`) is no longer accessible. Local simulation
remains valid for research; HIL mode is achieved instead via the ETSI 014
bridge to commercial discrete-variable hardware (ID Quantique / Toshiba).

License: Apache-2.0.
"""
from __future__ import annotations

import asyncio
import logging
import math
import os
import sys
import time
from hashlib import shake_256

import numpy as np

from ._skr import total_transmittance
from .base import BackendConfig, KeyProducer, RoundOutcome

log = logging.getLogger(__name__)

_AVAILABLE: bool | None = None


def _ensure_sf() -> bool:
    global _AVAILABLE
    if _AVAILABLE is not None:
        return _AVAILABLE
    candidate = os.environ.get("STRAWBERRYFIELDS_PATH", "/submodules/strawberryfields")
    if os.path.isdir(candidate) and candidate not in sys.path:
        sys.path.insert(0, candidate)
    try:
        import strawberryfields  # noqa: F401
        _AVAILABLE = True
    except Exception as e:
        log.warning("Strawberry Fields not importable (HIL/CV-QKD disabled): %s", e)
        _AVAILABLE = False
    return _AVAILABLE


def _bosonic_entropy(nu: float) -> float:
    """von Neumann entropy of a thermal state with symplectic eigenvalue nu.

    g(nu) = ((nu+1)/2) log2((nu+1)/2) - ((nu-1)/2) log2((nu-1)/2), with the
    vacuum at nu = 1 giving zero. Written in SNU where the vacuum symplectic
    eigenvalue is 1, which is the convention the rest of this module uses.
    """
    if nu <= 1.0:
        return 0.0
    hi = (nu + 1.0) / 2.0
    lo = (nu - 1.0) / 2.0
    return hi * math.log2(hi) - (lo * math.log2(lo) if lo > 0.0 else 0.0)


def thermal_photons_for_excess_noise(T: float, xi: float) -> float:
    """Strawberry Fields `ThermalLossChannel` nbar giving excess noise `xi`.

    Measured from the simulator rather than assumed: a homodyne x measurement
    after `ThermalLossChannel(T, nbar)` has variance T + (1-T)(2*nbar + 1) in
    SNU. Requiring that to equal the CV-QKD convention 1 + T*xi gives

        nbar = T * xi / (2 * (1 - T))

    The previous code passed `xi` straight in as `nbar`, which is a different
    quantity in a different place in the formula.
    """
    if T >= 1.0 or T <= 0.0:
        return 0.0
    return T * xi / (2.0 * (1.0 - T))


def gg02_asymptotic_skr(*, V_A: float, T: float, xi: float, beta: float) -> float:
    """GG02 reverse-reconciliation secret-key rate, homodyne detection, SNU.

    Laudenbach et al., "Continuous-Variable QKD with Gaussian Modulation --
    The Theory of Practical Implementations", Adv. Quantum Technol. 1, 1800011
    (2018), Sec. 5; equivalently Pirandola et al., Adv. Opt. Photon. 12, 1012
    (2020).

        R = beta * I(A:B) - chi(B:E)

    with the Holevo bound taken from the symplectic eigenvalues of the joint
    covariance matrix rather than a scalar stand-in:

        a = V,  b = T (V + chi_line),  c = sqrt(T (V^2 - 1))
        chi_line = (1 - T)/T + xi
        nu_{1,2}^2 = 1/2 [ Delta +/- sqrt(Delta^2 - 4 D^2) ]
        nu_3 = sqrt( a (a - c^2 / b) )        (Alice conditioned on Bob's homodyne)
        chi(B:E) = g(nu_1) + g(nu_2) - g(nu_3)

    The previous implementation used `chi(B:E) ~ g((V_B + 1)/2)`, described as
    a worst-case bound. It is not a bound so much as an unrelated quantity: it
    exceeded I(A:B) for every physically reasonable parameter set, so the rate
    was identically zero and the backend could never produce a key. Sanity
    checks that a rate must satisfy -- positive over a lossless channel,
    falling with distance, vanishing above a null-key excess noise -- are in
    tests/test_cvqkd_is_a_cv_protocol.py.
    """
    if T <= 0.0 or V_A <= 0.0 or beta <= 0.0:
        return 0.0

    V = V_A + 1.0                      # Alice's mode variance, modulation + shot
    chi_line = (1.0 - T) / T + xi      # channel-added noise referred to the input

    a = V
    b = T * (V + chi_line)
    c = math.sqrt(max(T * (V * V - 1.0), 0.0))

    D = a * b - c * c
    Delta = a * a + b * b - 2.0 * c * c
    disc = max(Delta * Delta - 4.0 * D * D, 0.0)
    nu1 = math.sqrt(max((Delta + math.sqrt(disc)) / 2.0, 0.0))
    nu2 = math.sqrt(max((Delta - math.sqrt(disc)) / 2.0, 0.0))
    nu3 = math.sqrt(max(a * (a - c * c / b), 0.0)) if b > 0.0 else 1.0

    chi_BE = _bosonic_entropy(nu1) + _bosonic_entropy(nu2) - _bosonic_entropy(nu3)
    I_AB = 0.5 * math.log2((V + chi_line) / (1.0 + chi_line))

    return max(beta * I_AB - chi_BE, 0.0)


def estimate_channel(alice_x: np.ndarray, bob_x: np.ndarray) -> tuple[float, float]:
    """Recover (T, xi) from the homodyne record, as a real receiver would.

    Bob's quadrature is sqrt(T) * <x_A> plus noise of variance 1 + T*xi in SNU,
    so the regression slope estimates sqrt(T) and the residual variance gives
    the excess noise. Estimating from the data rather than reading the
    configured values back is what makes the acceptance decision reflect the
    channel that was actually simulated.

    NOT a security-grade estimate, and the difference matters in the optimistic
    direction. These are point estimates with no finite-size confidence bound,
    and `xi` is clamped at zero because a negative variance is unphysical --
    so at a batch size where T*xi sits below the estimator's resolution (the
    default configuration gives T*xi = 0.0013 against a residual variance near
    1.0) the excess noise reads as zero and the rate comes out slightly high.
    A real receiver would use the upper confidence bound on xi, which is
    strictly more conservative. Recorded here rather than in a comment on the
    call site because it bounds what the reported rate may be claimed to mean.
    """
    var_a = float(np.var(alice_x))
    if var_a <= 0.0:
        return 0.0, 0.0
    slope = float(np.cov(bob_x, alice_x, bias=True)[0, 1] / var_a)
    T_est = min(max(slope * slope, 0.0), 1.0)
    residual = float(np.var(bob_x - slope * alice_x))
    xi_est = (residual - 1.0) / T_est if T_est > 0.0 else 0.0
    return T_est, max(xi_est, 0.0)


def _run_round_sync(cfg: BackendConfig) -> tuple[bytes, float, int, int, float, dict]:
    """Local Strawberry Fields homodyne simulation; return key + statistics."""
    import strawberryfields as sf
    from strawberryfields import ops

    V_A = cfg.cvqkd_V_A
    xi = cfg.cvqkd_xi
    T = total_transmittance(
        cfg.detector_efficiency, cfg.fiber_attenuation_db_per_km, cfg.link_length_km,
    )
    phi = math.radians(cfg.cvqkd_phi_deg)
    n_pulses = max(cfg.bb84_batch_size, 8)
    rng = np.random.default_rng(cfg.rng_seed)

    # Alice's modulation (Gaussian).
    #
    # Strawberry Fields runs at hbar = 2, where Coherent(alpha) has <x> = 2*alpha
    # and the vacuum has unit x-variance. A per-quadrature modulation variance of
    # V_A in SNU therefore needs sigma_alpha = sqrt(V_A)/2, not sqrt(V_A/2):
    # the latter puts 2*V_A on the channel. Both the factor and the vacuum
    # normalisation were measured against this build of the simulator rather
    # than taken from the paper's conventions.
    sigma_alpha = math.sqrt(V_A) / 2.0
    alpha_x = rng.normal(0.0, sigma_alpha, size=n_pulses)
    alpha_p = rng.normal(0.0, sigma_alpha, size=n_pulses)
    alpha_r = np.hypot(alpha_x, alpha_p)
    alpha_phi = np.arctan2(alpha_p, alpha_x)

    # Use a fast backend (gaussian) — fock is too slow for ~thousands of pulses
    prog = sf.Program(1)
    with prog.context as q:
        ops.Sgate(0.0) | q[0]  # placeholder

    # One thermal-loss channel, not two. The previous code applied
    # LossChannel(T) and then ThermalLossChannel(T, xi), so the transmittance
    # was squared -- 0.126 became 0.016 -- and passed the excess noise in as a
    # mean thermal photon number. Together those buried the signal in shot
    # noise, which is why the live demo measured a sign-disagreement of 0.443
    # (a T^2 channel predicts 0.42; the intended T predicts 0.30).
    nbar = thermal_photons_for_excess_noise(T, xi)

    measurements = np.empty(n_pulses, dtype=np.float64)
    eng = sf.Engine(backend="gaussian")
    for i in range(n_pulses):
        prog_i = sf.Program(1)
        with prog_i.context as q:
            # Polar form, NOT `Coherent(alpha_x, alpha_p)`.
            #
            # Strawberry Fields' two-argument signature is `Coherent(r, phi)`
            # with phi a PHASE IN RADIANS, so the original call rotated each
            # state by its own p-quadrature value instead of displacing it.
            # Confirmed against the library: Coherent(1, pi/2) measures <x> = 0.
            # Cost: the transmitted x came out scaled by E[cos(alpha_p)] =
            # exp(-sigma^2/2) = 0.607, matching the 0.591 attenuation seen in
            # the recovered slope. This build also rejects a complex argument,
            # so the conversion is explicit.
            ops.Coherent(alpha_r[i], alpha_phi[i]) | q[0]
            ops.ThermalLossChannel(T, nbar) | q[0]
            ops.MeasureHomodyne(phi) | q[0]
        result = eng.run(prog_i)
        measurements[i] = float(result.samples[0][0])
        eng.reset()

    # Alice's transmitted quadrature in the same units Bob measures.
    alice_x = 2.0 * alpha_x
    T_est, xi_est = estimate_channel(alice_x, measurements)
    skr = gg02_asymptotic_skr(V_A=V_A, T=T_est, xi=xi_est, beta=cfg.cvqkd_beta)

    # Sign agreement of the raw slice. Reported as a diagnostic ONLY.
    #
    # This is NOT a QBER in the BB84 sense and must not be gated on one. Under
    # loss it tends to 0.5 by construction, because a Gaussian-modulated
    # quadrature spends much of its time within a shot noise of zero -- that is
    # what reverse reconciliation exists to handle, and it is why the DV abort
    # threshold of 0.11 rejected 165 of 165 rounds on the public demo while the
    # protocol itself was fine.
    bob_bits = (measurements > 0).astype(np.uint8)
    alice_bits = (alice_x > 0).astype(np.uint8)
    slice_disagreement = float(np.mean(bob_bits ^ alice_bits)) if n_pulses else 1.0

    # The CV null-key condition: no key exists when the Holevo bound overtakes
    # the reconciled mutual information.
    est = {
        "T_configured": T, "T_estimated": T_est,
        "xi_configured": xi, "xi_estimated": xi_est,
        "slice_disagreement": slice_disagreement,
    }
    if skr <= 0.0:
        return b"", slice_disagreement, 0, n_pulses, 0.0, est

    raw_bytes = bob_bits.tobytes()
    key = shake_256(raw_bytes).digest(cfg.out_bits_per_key // 8)
    return key, slice_disagreement, n_pulses, n_pulses, skr, est


class CVQKDBackend(KeyProducer):
    backend_name = "cvqkd"

    def __init__(self, cfg: BackendConfig):
        super().__init__(cfg)
        if not _ensure_sf():
            raise RuntimeError(
                "Strawberry Fields not available. Install via `pip install strawberryfields`",
            )

    async def run_round(self) -> RoundOutcome:
        t0 = time.perf_counter()
        try:
            key, qber, sifted, n, skr_pp, est = await asyncio.to_thread(
                _run_round_sync, self.cfg,
            )
        except Exception as e:
            log.warning("CV-QKD round failed: %s", e)
            return RoundOutcome(
                accepted=False, qber=1.0, key_bytes=b"",
                n_photons=self.cfg.bb84_batch_size, n_sifted=0, intercepted=0,
                elapsed_ms=(time.perf_counter() - t0) * 1000.0,
                backend_meta={"backend": "cvqkd", "error": str(e)},
            )
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        return RoundOutcome(
            accepted=bool(key),
            qber=qber,
            key_bytes=key,
            n_photons=n,
            n_sifted=sifted,
            intercepted=0,
            elapsed_ms=elapsed_ms,
            skr_bps=skr_pp * self.cfg.pulse_rate_hz,
            # `qber` carries the raw-slice sign disagreement, which for a
            # continuous-variable protocol is a diagnostic and not an error
            # rate to threshold. Said here so a reader of the API sees it.
            backend_meta={
                "backend": "cvqkd", "protocol": "GG02",
                "qber_is": "raw-slice sign disagreement, not a DV QBER",
                "accepted_on": "GG02 null-key condition (skr > 0)",
                **est,
                **self.eve_meta(),
            },
        )
