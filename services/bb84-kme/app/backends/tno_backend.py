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

from .. import config_loader as cl
from ._skr import accepts_round, qber_Emu, total_transmittance
from .base import BackendConfig, KeyProducer, RoundOutcome

log = logging.getLogger(__name__)


def _build_detector(cfg: BackendConfig):
    """Build a TNO Detector from config/qkd_params.yaml.

    Every timing characteristic comes from the `detector:` block. They were
    previously literals here, which contradicted this module's own docstring
    ("nothing is hardcoded") and was the standing failure in
    tests/test_no_hardcoded_params.py.
    """
    from tno.quantum.communication.qkd_key_rate.quantum import Detector

    return Detector(
        name="pqcqkd",
        efficiency_detector=float(cfg.detector_efficiency),
        efficiency_system=float(cl.require("detector.efficiency_system")),
        dark_count_frequency=float(cfg.dark_count_rate_hz),
        polarization_drift=float(cfg.misalignment_error_ed),
        error_detector=float(cfg.misalignment_error_ed),
        jitter_source=float(cl.require("detector.jitter_source_s")),
        jitter_detector=float(cl.require("detector.jitter_detector_s")),
        dead_time=float(cl.require("detector.dead_time_s")),
        detection_frequency=float(cl.require("detector.detection_frequency_hz")),
        detection_window=int(cl.require("detector.detection_window")),
    )


_SOURCE = "tno.quantum.communication.qkd_key_rate v2.0.4 (Apache-2.0)"

# TNO signals "I converged, and the answer is that no key is extractable" by
# RAISING, not by returning a number:
#
#   bb84.py:593-595   if rate < 0:
#                         error_msg = "Optimization resulted in a negative key rate."
#                         raise ValueError(error_msg)
#
# That is a RESULT, not a failure. `compute_tno_rate` already clamps a negative
# rate with `max(0.0, rate)` -- the clamp simply never sees one, because the
# optimiser raises before returning.
#
# Measured on the live demo before this was fixed: at 254-300 km the decoy
# estimate raised, the fully-asymptotic fallback raised too, the second raise
# propagated to main.py's `except Exception`, and /verify reported
#
#   verdict: "engine_unavailable"   error: "Optimization resulted in a negative
#                                           key rate."
#
# The engine was installed, ran, and answered. Calling that "unavailable" is
# the same inversion that `neither_predicts_a_key` was introduced to remove,
# one layer further down: the closed form said 0, TNO said 0, and the page
# reported that the cross-check had not run.
#
# Matched on type AND message because ValueError is also what a genuinely bad
# input raises, and those must keep propagating. The message is upstream
# English and could change, so tests/test_tno_no_key_is_not_no_engine.py pins
# it against the vendored source -- if TNO rewords it, that test fails rather
# than this silently reverting to "engine_unavailable".
_NO_KEY_MARKER = "negative key rate"


def _is_converged_no_key(exc: BaseException) -> bool:
    """True when TNO optimised successfully and found no extractable key."""
    return isinstance(exc, ValueError) and _NO_KEY_MARKER in str(exc).lower()


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
    # Distinguishes "TNO says no key" from "TNO could not be asked". Both used
    # to leave this function by the same route.
    no_key = False
    try:
        est = BB84AsymptoticKeyRateEstimate(detector=detector, number_of_decoy=2)
        params, rate = est.optimize_rate(attenuation=attenuation_db)
        mu_opt = float(next(iter(params.values()))[0]) if params else None
    except Exception as e:
        if _is_converged_no_key(e):
            # Do NOT fall back here. The fallback is a DIFFERENT and more
            # optimistic model -- fully-asymptotic assumes infinitely many decoy
            # states -- so using it to second-guess a converged decoy answer
            # would report a rate for a protocol we do not run. The decoy
            # estimate is the one that matches the shipped source.
            log.info("TNO decoy estimate: no extractable key at %.1f dB (%s)",
                     attenuation_db, e)
            return {
                "rate_per_pulse": 0.0,
                "skr_bps": 0.0,
                "mu_opt": None,
                "attenuation_db": attenuation_db,
                "protocol": protocol,
                # The caller must be able to tell a converged zero from a zero
                # that came from somewhere else.
                "no_key_reason": str(e),
                "source": _SOURCE,
            }
        log.warning("TNO decoy estimate failed (%s); trying fully-asymptotic", e)
        protocol = "BB84 (fully asymptotic)"
        est2 = BB84FullyAsymptoticKeyRateEstimate(detector=detector)
        try:
            params, rate = est2.optimize_rate(attenuation=attenuation_db)
            mu_opt = float(next(iter(params.values()))[0]) if params else None
        except Exception as e2:
            # The second raise used to propagate untouched, which is how a
            # converged "no key" reached the UI as "engine_unavailable".
            if not _is_converged_no_key(e2):
                raise
            log.info("TNO fully-asymptotic: no extractable key at %.1f dB (%s)",
                     attenuation_db, e2)
            rate, mu_opt, no_key = 0.0, None, str(e2)

    rate = max(0.0, float(rate))
    out = {
        "rate_per_pulse": rate,
        "skr_bps": rate * float(cfg.pulse_rate_hz),
        "mu_opt": mu_opt,
        "attenuation_db": attenuation_db,
        "protocol": protocol,
        "source": _SOURCE,
    }
    if no_key:
        out["no_key_reason"] = no_key
    return out


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

        # This backend already had the two-condition predicate right; it is now
        # the shared one, so simqn and sequence cannot drift back to a
        # threshold-only test. Multiplying by pulse_rate_hz changes no sign.
        accepted = accepts_round(
            qber, res["rate_per_pulse"] * self.cfg.pulse_rate_hz, self.cfg)
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
