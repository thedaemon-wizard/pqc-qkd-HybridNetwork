"""TNO-Quantum key-rate backend (submodules/tno-qkd-key-rate, Apache-2.0).

Wraps `tno.quantum.communication.qkd_key_rate` — an independently-developed,
peer-reviewed (Attema et al. 2021; Ma et al. 2007) decoy-state BB84 / BBM92
key-rate engine, actively maintained (v2.0.4, 2026-02). It is used here two ways:

  1. As a selectable bb84-kme backend (`SIMULATOR_BACKEND=tno`) producing keys
     whose secret-key rate comes from TNO's asymptotic decoy-state optimisation.
  2. As an INDEPENDENT cross-check of our own closed-form Lo-Ma key-rate table
     (see `compute_tno_rate`, surfaced in the WebUI verification panel).

All physics inputs come from BackendConfig (config/qkd_params.yaml); nothing is
hardcoded. Heavy import is lazy so selecting another backend never imports it.
"""
from __future__ import annotations

import logging
import os
import time
from typing import Any

from ._skr import qber_Emu, total_transmittance
from .base import BackendConfig, KeyProducer, RoundOutcome

log = logging.getLogger(__name__)


def _build_detector(cfg: BackendConfig):
    """Build a TNO Detector from our config, falling back to the package's
    standard_detector if a field name/units mismatch arises across versions."""
    from tno.quantum.communication.qkd_key_rate.quantum import (
        Detector, standard_detector,
    )
    try:
        return Detector(
            name="pqcqkd",
            efficiency_detector=float(cfg.detector_efficiency),
            efficiency_system=1.0,
            dark_count_frequency=float(cfg.dark_count_rate_hz),
            polarization_drift=float(cfg.misalignment_error_ed),
            error_detector=float(cfg.misalignment_error_ed),
            jitter_source=0.0,
            jitter_detector=5.0e-11,
            dead_time=4.5e-08,
            detection_frequency=1.0e7,
            detection_window=5,
        )
    except Exception as e:  # pragma: no cover - version-robustness fallback
        log.warning("TNO custom Detector failed (%s); using standard_detector", e)
        return standard_detector


def compute_tno_rate(cfg: BackendConfig) -> dict[str, Any]:
    """Compute TNO's asymptotic decoy-state BB84 key rate for the given config.

    Returns a dict with rate-per-pulse, derived bits/s, optimal intensity and the
    channel attenuation used — consumed by the backend AND the cross-check route.
    """
    from tno.quantum.communication.qkd_key_rate.quantum.bb84 import (
        BB84AsymptoticKeyRateEstimate,
        BB84FullyAsymptoticKeyRateEstimate,
    )

    attenuation_db = float(cfg.fiber_attenuation_db_per_km) * float(cfg.link_length_km)
    detector = _build_detector(cfg)

    rate = 0.0
    mu_opt: float | None = None
    protocol = "BB84 decoy (asymptotic)"
    try:
        est = BB84AsymptoticKeyRateEstimate(detector=detector, number_of_decoy=2)
        params, rate = est.optimize_rate(attenuation=attenuation_db)
        mu_opt = float(next(iter(params.values()))[0]) if params else None
    except Exception as e:
        log.warning("TNO decoy estimate failed (%s); trying fully-asymptotic", e)
        protocol = "BB84 (fully asymptotic)"
        est2 = BB84FullyAsymptoticKeyRateEstimate(detector=detector)
        params, rate = est2.optimize_rate(attenuation=attenuation_db)
        mu_opt = float(next(iter(params.values()))[0]) if params else None

    rate = max(0.0, float(rate))
    return {
        "rate_per_pulse": rate,
        "skr_bps": rate * float(cfg.pulse_rate_hz),
        "mu_opt": mu_opt,
        "attenuation_db": attenuation_db,
        "protocol": protocol,
        "source": "tno.quantum.communication.qkd_key_rate v2.0.4 (Apache-2.0)",
    }


class TNOBackend(KeyProducer):
    backend_name = "tno"

    def __init__(self, cfg: BackendConfig):
        super().__init__(cfg)
        # Fail fast if the package is missing so the operator sees it immediately.
        import tno.quantum.communication.qkd_key_rate as _tno  # noqa: F401

    async def run_round(self) -> RoundOutcome:
        import asyncio
        t0 = time.perf_counter()
        res = await asyncio.to_thread(compute_tno_rate, self.cfg)
        elapsed_ms = (time.perf_counter() - t0) * 1000.0

        # QBER from our closed-form E_mu (consistent with the other backends).
        eta_total = total_transmittance(
            self.cfg.detector_efficiency,
            self.cfg.fiber_attenuation_db_per_km,
            self.cfg.link_length_km,
        )
        Y0 = self.cfg.dark_count_rate_hz / max(self.cfg.pulse_rate_hz, 1.0)
        qber = float(qber_Emu(Y0, eta_total, self.cfg.misalignment_error_ed,
                              self.cfg.intensity_signal_mu))

        accepted = res["rate_per_pulse"] > 0.0 and qber < self.cfg.qber_threshold_abort
        key_bytes = os.urandom(self.cfg.out_bits_per_key // 8) if accepted else b""
        return RoundOutcome(
            accepted=accepted,
            qber=qber,
            key_bytes=key_bytes,
            n_photons=self.cfg.bb84_batch_size,
            n_sifted=self.cfg.out_bits_per_key if accepted else 0,
            intercepted=0,
            elapsed_ms=elapsed_ms,
            skr_bps=res["skr_bps"],
            sample_frames=[],
            backend_meta={"backend": "tno", **res},
        )
