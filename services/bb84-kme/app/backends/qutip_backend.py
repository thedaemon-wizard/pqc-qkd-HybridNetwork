"""QuTiP backend — wraps the original physics simulator under the new ABC.

Pulls all numeric tunables from BackendConfig (which itself is loaded from
config/qkd_params.yaml). Nothing here is hardcoded.
"""
from __future__ import annotations

import asyncio
import logging
import time

import numpy as np

from ..bb84.simulator import RoundConfig, run_round
from ._skr import skr_bps_from_config
from .base import BackendConfig, KeyProducer, RoundOutcome

log = logging.getLogger(__name__)


class QuTiPBackend(KeyProducer):
    backend_name = "qutip"
    # The one backend that passes eve_enabled into its channel model (see the
    # simulate_round call below). Every other backend leaves this False and
    # declares the omission through KeyProducer.eve_meta().
    models_eve = True

    def __init__(self, cfg: BackendConfig):
        super().__init__(cfg)
        self._rng = (
            np.random.default_rng(cfg.rng_seed)
            if cfg.rng_seed is not None
            else np.random.default_rng()
        )

    def _round_cfg(self) -> RoundConfig:
        # All values derived from BackendConfig — no literals here
        # The original QuTiP simulator uses a simplified channel; we feed it
        # the depolarizing prob that matches the closed-form drop rate.
        from ._skr import drop_rate_for_simulator, total_transmittance
        Y0 = self.cfg.dark_count_rate_hz / max(self.cfg.pulse_rate_hz, 1.0)
        eta_total = total_transmittance(
            self.cfg.detector_efficiency,
            self.cfg.fiber_attenuation_db_per_km,
            self.cfg.link_length_km,
        )
        # Use 1 - exp(-eta_total*mu) as success prob; convert to bit-flip prob
        channel_noise = min(self.cfg.misalignment_error_ed
                            + drop_rate_for_simulator(Y0=Y0, eta_total=eta_total,
                                                       mu=self.cfg.intensity_signal_mu)
                              * self.cfg.after_pulse_prob,
                            0.5)
        return RoundConfig(
            n_photons=self.cfg.bb84_batch_size,
            channel_noise=channel_noise,
            eve_enabled=self.cfg.eve_enabled,
            eve_prob=self.cfg.eve_intercept_prob,
            qber_threshold=self.cfg.qber_threshold_abort,
            out_bits=self.cfg.out_bits_per_key,
        )

    async def run_round(self) -> RoundOutcome:
        t0 = time.perf_counter()
        result = await asyncio.to_thread(run_round, self._round_cfg(), rng=self._rng)
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        # n_sifted/n_photons is the SIFTING fraction, not a secret-key rate:
        # it counts pulses surviving basis reconciliation, before error
        # correction leaks f_EC*h2(E_mu) and privacy amplification removes
        # Eve's information. Use the shared GLLP/Lo-Ma model instead.
        skr_bps = skr_bps_from_config(self.cfg)
        return RoundOutcome(
            accepted=result.accepted,
            qber=result.qber,
            key_bytes=result.key_bytes,
            n_photons=result.n_photons,
            n_sifted=result.n_sifted,
            intercepted=result.intercepted,
            elapsed_ms=elapsed_ms,
            skr_bps=skr_bps,
            sample_frames=result.sample_frames,
            backend_meta={"backend": "qutip"},
        )
