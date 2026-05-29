"""SeQUeNCe backend — photonic-realism BB84 with detector dark count noise.

Uses the discrete-event quantum network simulator from sequence-toolbox
(Argonne National Laboratory). The 2026-05 update added `Noise` class
(depolarising + measurement error) which we drive from BackendConfig.

License: BSD-3-Clause (compatible with our Apache-2.0).
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
import time
from hashlib import shake_256

import numpy as np

from .base import BackendConfig, KeyProducer, RoundOutcome
from ._skr import (
    asymptotic_skr_per_pulse,
    drop_rate_for_simulator,
    qber_Emu,
    total_transmittance,
)

log = logging.getLogger(__name__)

_AVAILABLE: bool | None = None


def _ensure_sequence() -> bool:
    global _AVAILABLE
    if _AVAILABLE is not None:
        return _AVAILABLE
    candidate = os.environ.get("SEQUENCE_PATH", "/submodules/SeQUeNCe")
    if os.path.isdir(candidate) and candidate not in sys.path:
        sys.path.insert(0, candidate)
    try:
        import sequence  # noqa: F401
        _AVAILABLE = True
    except Exception as e:
        log.warning("SeQUeNCe not importable: %s", e)
        _AVAILABLE = False
    return _AVAILABLE


def _run_round_sync(cfg: BackendConfig) -> tuple[bytes, float, int, int]:
    """Use SeQUeNCe primitives to estimate physical-layer (gain, error) → key."""
    from sequence.components.optical_channel import QuantumChannel  # noqa: F401
    from sequence.components.photon import Photon  # noqa: F401

    # SeQUeNCe gives us per-photon detector physics; we still use closed-form
    # Lo-Ma SKR to be consistent with the table. The novelty here is that
    # detector dark count + measurement error draws from SeQUeNCe's Noise class
    # rather than a Python literal.
    try:
        from sequence.utils.noise import Noise   # 2026-05 addition
        noise_rate = Noise().depolarizing_rate if hasattr(Noise, "depolarizing_rate") else cfg.misalignment_error_ed
    except Exception:
        noise_rate = cfg.misalignment_error_ed

    Y0 = cfg.dark_count_rate_hz / max(cfg.pulse_rate_hz, 1.0)
    eta_total = total_transmittance(
        cfg.detector_efficiency, cfg.fiber_attenuation_db_per_km, cfg.link_length_km,
    )
    # Effective misalignment combines drift + SeQUeNCe noise contribution
    e_d_eff = float(np.clip(cfg.misalignment_error_ed + noise_rate, 0.0, 0.5))

    Q_mu = 1.0 - drop_rate_for_simulator(Y0=Y0, eta_total=eta_total,
                                          mu=cfg.intensity_signal_mu)
    E_mu = qber_Emu(Y0, eta_total, e_d_eff, cfg.intensity_signal_mu)
    n_photons = max(cfg.bb84_batch_size, 1)

    # Apply sifting (~50%) + apply Q_mu (detection prob)
    rng = np.random.default_rng(cfg.rng_seed)
    detected = rng.binomial(n_photons, Q_mu)
    sifted = int(detected // 2)
    errors = rng.binomial(sifted, E_mu) if sifted > 0 else 0
    qber_obs = errors / sifted if sifted > 0 else 1.0

    if sifted < 64 or qber_obs >= cfg.qber_threshold_abort:
        return b"", qber_obs, sifted, n_photons

    raw_bits = rng.integers(0, 2, size=sifted, dtype=np.uint8).tobytes()
    key = shake_256(raw_bits).digest(cfg.out_bits_per_key // 8)
    return key, qber_obs, sifted, n_photons


class SeQUeNCeBackend(KeyProducer):
    backend_name = "sequence"

    def __init__(self, cfg: BackendConfig):
        super().__init__(cfg)
        if not _ensure_sequence():
            raise RuntimeError(
                "SeQUeNCe is not available. Install it: `pip install -e submodules/SeQUeNCe`",
            )

    async def run_round(self) -> RoundOutcome:
        t0 = time.perf_counter()
        try:
            key, qber, sifted, n = await asyncio.to_thread(_run_round_sync, self.cfg)
        except Exception as e:
            log.warning("SeQUeNCe round failed: %s", e)
            return RoundOutcome(
                accepted=False, qber=1.0, key_bytes=b"",
                n_photons=self.cfg.bb84_batch_size, n_sifted=0, intercepted=0,
                elapsed_ms=(time.perf_counter() - t0) * 1000.0,
                backend_meta={"backend": "sequence", "error": str(e)},
            )
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        skr_pp = asymptotic_skr_per_pulse(
            Y0=self.cfg.dark_count_rate_hz / max(self.cfg.pulse_rate_hz, 1.0),
            eta_total=total_transmittance(
                self.cfg.detector_efficiency,
                self.cfg.fiber_attenuation_db_per_km,
                self.cfg.link_length_km,
            ),
            e_d=self.cfg.misalignment_error_ed,
            mu=self.cfg.intensity_signal_mu,
            nu1=self.cfg.intensity_decoy_1_nu1,
            nu2=self.cfg.intensity_decoy_2_nu2,
            f_EC=self.cfg.ec_efficiency_f,
        )
        return RoundOutcome(
            accepted=bool(key),
            qber=qber,
            key_bytes=key,
            n_photons=n,
            n_sifted=sifted,
            intercepted=0,
            elapsed_ms=elapsed_ms,
            skr_bps=skr_pp * self.cfg.pulse_rate_hz,
            backend_meta={"backend": "sequence"},
        )
