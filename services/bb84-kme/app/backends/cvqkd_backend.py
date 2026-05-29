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

from .base import BackendConfig, KeyProducer, RoundOutcome
from ._skr import total_transmittance

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


def _gg02_asymptotic_skr(*, V_A: float, T: float, xi: float, beta: float) -> float:
    """GG02 reverse-reconciliation SKR (shot-noise units), reverse rec, lossy
    channel. Conservative analytic form from Pirandola Adv. Opt. Photon. 12, 1012 (2020).

    R = β · I(A:B) − χ(B:E)
    I(A:B) = 0.5 · log2(1 + V_A · T / (1 + T·xi))    (heterodyne ≈ Gaussian)
    χ(B:E) ≈ g((V_B + 1)/2)    (worst-case purification upper bound)
    """
    if T <= 0 or V_A <= 0:
        return 0.0
    V_B = T * V_A + T * xi + 1.0
    I_AB = 0.5 * math.log2(1.0 + V_A * T / (1.0 + T * xi))

    def g(x: float) -> float:
        if x <= 0.5:
            return 0.0
        return (x + 0.5) * math.log2(x + 0.5) - (x - 0.5) * math.log2(x - 0.5)

    chi_BE = g((V_B + 1.0) / 2.0)
    return max(beta * I_AB - chi_BE, 0.0)


def _run_round_sync(cfg: BackendConfig) -> tuple[bytes, float, int, int, float]:
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

    # Alice's modulation (Gaussian)
    alpha_x = rng.normal(0.0, math.sqrt(V_A / 2.0), size=n_pulses)
    alpha_p = rng.normal(0.0, math.sqrt(V_A / 2.0), size=n_pulses)

    # Use a fast backend (gaussian) — fock is too slow for ~thousands of pulses
    prog = sf.Program(1)
    with prog.context as q:
        ops.Sgate(0.0) | q[0]  # placeholder

    measurements = np.empty(n_pulses, dtype=np.float64)
    eng = sf.Engine(backend="gaussian")
    for i in range(n_pulses):
        prog_i = sf.Program(1)
        with prog_i.context as q:
            ops.Coherent(alpha_x[i], alpha_p[i]) | q[0]
            ops.LossChannel(T) | q[0]
            ops.ThermalLossChannel(T, xi) | q[0]
            ops.MeasureHomodyne(phi) | q[0]
        result = eng.run(prog_i)
        measurements[i] = float(result.samples[0][0])
        eng.reset()

    # Sliced reconciliation surrogate: keep sign of homodyne quadrature
    bob_bits = (measurements > 0).astype(np.uint8)
    alice_bits = (alpha_x > 0).astype(np.uint8)
    errors = int(np.sum(bob_bits ^ alice_bits))
    qber = errors / n_pulses if n_pulses else 1.0

    if qber >= cfg.qber_threshold_abort:
        return b"", qber, 0, n_pulses, 0.0

    raw_bytes = bob_bits.tobytes()
    key = shake_256(raw_bytes).digest(cfg.out_bits_per_key // 8)
    skr = _gg02_asymptotic_skr(V_A=V_A, T=T, xi=xi, beta=cfg.cvqkd_beta)
    return key, qber, n_pulses, n_pulses, skr


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
            key, qber, sifted, n, skr_pp = await asyncio.to_thread(_run_round_sync, self.cfg)
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
            backend_meta={"backend": "cvqkd", "protocol": "GG02"},
        )
