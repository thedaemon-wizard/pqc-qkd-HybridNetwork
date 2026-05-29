"""Composite backend: SimQN physical layer feeds qkdnetsim network layer.

Implements the "end-to-end pipeline" described in Phase 8-B-7 of the plan:
    physical (SimQN) → KMS (qkdnetsim) → arnika consumes ETSI 014

Architecture:
1. SimQN computes a realistic per-link keyRate (bits/sec) using fiber loss,
   detector efficiency, dark counts, and the closed-form gain/QBER.
2. We POST that keyRate to the qkdnetsim-kme container, which uses it as
   the `DataRate` parameter for its NS-3 `QuantumChannel` and serves keys
   over its ETSI 014 endpoint.
3. This backend then pulls the served keys via the proxy.

The composite gives us the most defensible "real-hardware-like" pipeline
without owning real QKD hardware.
"""
from __future__ import annotations

import logging
import time

import httpx

from ._skr import asymptotic_skr_per_pulse, total_transmittance
from .base import BackendConfig, KeyProducer, RoundOutcome
from .qkdnetsim_proxy import QKDNetSimProxyBackend

log = logging.getLogger(__name__)


class CompositeBackend(KeyProducer):
    backend_name = "composite_sim_to_net"

    def __init__(self, cfg: BackendConfig):
        super().__init__(cfg)
        self._proxy = QKDNetSimProxyBackend(cfg)
        self._last_pushed_rate = -1.0

    async def _push_rate_to_net(self) -> float:
        """Compute keyRate from physical model and inform qkdnetsim KME."""
        Y0 = self.cfg.dark_count_rate_hz / max(self.cfg.pulse_rate_hz, 1.0)
        eta = total_transmittance(
            self.cfg.detector_efficiency,
            self.cfg.fiber_attenuation_db_per_km,
            self.cfg.link_length_km,
        )
        skr_pp = asymptotic_skr_per_pulse(
            Y0=Y0, eta_total=eta, e_d=self.cfg.misalignment_error_ed,
            mu=self.cfg.intensity_signal_mu,
            nu1=self.cfg.intensity_decoy_1_nu1,
            nu2=self.cfg.intensity_decoy_2_nu2,
            f_EC=self.cfg.ec_efficiency_f,
        )
        rate_bps = skr_pp * self.cfg.pulse_rate_hz
        # Push only when rate changed by > threshold — coalesces rounding noise.
        # Threshold loaded from BackendConfig.extras when present.
        rate_change_threshold = float(self.cfg.extras.get(
            "composite_rate_change_threshold", 0.5))
        if abs(rate_bps - self._last_pushed_rate) > rate_change_threshold * max(self._last_pushed_rate, 1.0):
            try:
                async with httpx.AsyncClient(timeout=2.0) as client:
                    await client.post(
                        f"{self._proxy._url}/internal/set_rate",
                        json={"link": "alice-bob", "keyRate_bps": rate_bps},
                    )
                self._last_pushed_rate = rate_bps
            except Exception as e:    # pragma: no cover
                log.debug("rate push to qkdnetsim skipped (%s)", e)
        return rate_bps

    async def run_round(self) -> RoundOutcome:
        t0 = time.perf_counter()
        rate_bps = await self._push_rate_to_net()
        out = await self._proxy.run_round()
        out.elapsed_ms = (time.perf_counter() - t0) * 1000.0
        out.skr_bps = rate_bps
        out.backend_meta.update({"backend": "composite_sim_to_net",
                                  "physical_skr_bps": rate_bps})
        return out
