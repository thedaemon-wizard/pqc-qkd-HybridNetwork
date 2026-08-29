"""Backend abstractions — all numeric values flow through BackendConfig.

No literal numbers may live in any backend implementation; everything comes
from the central YAML, optionally overridden by Bayesian-Optimised values.
"""
from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class BackendConfig:
    """All numeric tunables a backend needs, fetched from qkd_params.yaml."""
    # physical
    fiber_attenuation_db_per_km: float
    link_length_km: float
    detector_efficiency: float
    dark_count_rate_hz: float
    after_pulse_prob: float
    misalignment_error_ed: float
    # source / WCP
    pulse_rate_hz: float
    intensity_signal_mu: float
    intensity_decoy_1_nu1: float
    intensity_decoy_2_nu2: float
    basis_bias_pz: float
    prob_signal_mu: float
    prob_decoy_1_nu1: float
    prob_decoy_2_nu2: float
    # protocol
    block_size_N: int
    security_epsilon: float
    correctness_epsilon: float
    ec_efficiency_f: float
    qber_threshold_abort: float
    out_bits_per_key: int
    # simulator-specific
    bb84_batch_size: int
    rng_seed: int | None = None
    # cv-qkd
    cvqkd_protocol: str = "GG02"
    cvqkd_V_A: float = 4.0
    cvqkd_xi: float = 0.01
    cvqkd_phi_deg: float = 0.0
    cvqkd_beta: float = 0.95
    # adversary
    eve_enabled: bool = False
    eve_intercept_prob: float = 0.0
    # composite / proxy
    qkdnetsim_proxy_url: str = ""
    extras: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class RoundOutcome:
    """Result of a single BB84 (or equivalent) round."""
    accepted: bool
    qber: float
    key_bytes: bytes              # exactly `out_bits_per_key/8` when accepted
    n_photons: int
    n_sifted: int
    intercepted: int
    elapsed_ms: float
    # Closed-form secret-key rate for THIS CONFIG, not a measurement of this
    # round. Every backend fills it from `skr_bps_from_config(cfg)`, whose
    # signature is `(cfg) -> float` -- there is no round argument, so two nodes
    # differing by thousands of rounds report bit-identical values. Surfaced as
    # `modelled_skr_bps` on /sim/stats for that reason; see keypool.PoolStats.
    #
    # The comment here previously read "estimated secret-key rate", which reads
    # as "measured, with error bars" rather than "predicted, from parameters".
    skr_bps: float = 0.0
    sample_frames: list[dict] = field(default_factory=list)
    backend_meta: dict[str, Any] = field(default_factory=dict)


class KeyProducer(abc.ABC):
    """Async ABC every backend implements."""

    backend_name: str = "base"

    def __init__(self, cfg: BackendConfig):
        self.cfg = cfg

    @abc.abstractmethod
    async def run_round(self) -> RoundOutcome:
        """Execute one round; must NOT use any hardcoded numeric constants."""

    def update_config(self, cfg: BackendConfig) -> None:
        """Hot-reload hook called when qkd_params.yaml changes."""
        self.cfg = cfg

    #: Whether `run_round` actually reads `cfg.eve_enabled`.
    #:
    #: Default False, so a backend that does nothing with Eve says so by
    #: omission rather than by silence. Only `qutip_backend` overrides it to
    #: True today -- it is the one backend that passes `eve_enabled` into its
    #: channel model. `simqn`, `sequence`, `cvqkd` and `tno` all hardcode
    #: `intercepted=0` and never look at the flag.
    models_eve: bool = False

    def set_eve(self, enabled: bool, prob: float) -> None:
        self.cfg.eve_enabled = enabled
        self.cfg.eve_intercept_prob = max(0.0, min(1.0, prob))

    def eve_meta(self) -> dict[str, Any]:
        """Marker fields to merge into `backend_meta` when Eve is ineffective.

        `POST /sim/eve` reported success on every backend, and the shipped
        default (`simqn`, per config/qkd_params.yaml) ignores Eve entirely:
        `intercepted=0` is a literal, and the flag is never read. Driven with
        `intercept_prob=1.0` the round still returned the QBER unchanged and
        `intercepted=0` -- so "Eve is not modelled here" and "Eve was modelled
        and found nothing" produced byte-identical output.

        `qkdnetsim_proxy` already solved this for itself. This lifts the same
        marker to the base class so the other four stop being silent too,
        rather than copying the block into four files.

        Returns an empty dict when there is nothing to declare, so callers can
        splat it unconditionally.
        """
        if self.models_eve or not self.cfg.eve_enabled:
            return {}
        return {
            "eve_ignored": True,
            "unmeasured": ["intercepted"],
            "note": (
                f"eve_enabled is set but {type(self).__name__} does not model "
                f"an eavesdropper: intercepted is reported as 0 because none "
                f"is simulated, not because none was detected"
            ),
        }


def cfg_from_yaml() -> BackendConfig:
    """Build a BackendConfig from the central YAML (and env overrides)."""
    from .. import config_loader as cl

    seed_val = cl.get("simulator.rng_seed", None)
    return BackendConfig(
        fiber_attenuation_db_per_km=float(cl.get("physical.fiber_attenuation_db_per_km")),
        link_length_km=float(cl.get("physical.link_length_km")),
        detector_efficiency=float(cl.get("physical.detector_efficiency")),
        dark_count_rate_hz=float(cl.get("physical.dark_count_rate_hz")),
        after_pulse_prob=float(cl.get("physical.after_pulse_prob")),
        misalignment_error_ed=float(cl.get("physical.misalignment_error_ed")),
        pulse_rate_hz=float(cl.get("source.pulse_rate_hz")),
        intensity_signal_mu=float(cl.get("source.intensity_signal_mu")),
        intensity_decoy_1_nu1=float(cl.get("source.intensity_decoy_1_nu1")),
        intensity_decoy_2_nu2=float(cl.get("source.intensity_decoy_2_nu2")),
        basis_bias_pz=float(cl.get("source.basis_bias_pz")),
        prob_signal_mu=float(cl.get("source.prob_signal_mu")),
        prob_decoy_1_nu1=float(cl.get("source.prob_decoy_1_nu1")),
        prob_decoy_2_nu2=float(cl.get("source.prob_decoy_2_nu2")),
        block_size_N=int(float(cl.get("protocol.block_size_N"))),
        security_epsilon=float(cl.get("protocol.security_epsilon")),
        correctness_epsilon=float(cl.get("protocol.correctness_epsilon")),
        ec_efficiency_f=float(cl.get("protocol.ec_efficiency_f")),
        qber_threshold_abort=float(cl.get("protocol.qber_threshold_abort")),
        out_bits_per_key=int(cl.get("protocol.out_bits_per_key")),
        bb84_batch_size=int(cl.get("simulator.bb84_batch_size")),
        rng_seed=None if seed_val is None else int(seed_val),
        cvqkd_protocol=str(cl.get("cvqkd.protocol", "GG02")),
        cvqkd_V_A=float(cl.get("cvqkd.modulation_variance_V_A", 4.0)),
        cvqkd_xi=float(cl.get("cvqkd.excess_noise_xi", 0.01)),
        cvqkd_phi_deg=float(cl.get("cvqkd.homodyne_phi_deg", 0.0)),
        cvqkd_beta=float(cl.get("cvqkd.reconciliation_efficiency_beta", 0.95)),
        eve_enabled=bool(cl.get("eve.enabled", False)),
        eve_intercept_prob=float(cl.get("eve.intercept_prob", 0.0)),
        qkdnetsim_proxy_url=str(cl.get("simulator.qkdnetsim_proxy_url", "") or ""),
    )
