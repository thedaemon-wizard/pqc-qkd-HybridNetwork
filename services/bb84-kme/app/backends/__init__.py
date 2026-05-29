"""Pluggable simulator backends for BB84/CV-QKD/MDI key production.

Selection is config-driven (`simulator.backend` in qkd_params.yaml, or env
`SIMULATOR_BACKEND`).  All backends implement the `KeyProducer` ABC and emit
256-bit keys through the same async interface so `keypool.py` does not care
which physics layer is running.

Backends:
    qutip      — built-in QuTiP photon sim (lightweight, the original PoC)
    simqn      — submodules/SimQN BB84SendApp/RecvApp (Cascade + Toeplitz PA)
    sequence   — submodules/SeQUeNCe photonic realism (SPDC noise, detector dark)
    cvqkd      — submodules/strawberryfields GG02 (continuous variable)
    composite  — SimQN physical + qkdnetsim network (most realistic)
    qkdnetsim_proxy — proxy to external NS-3 KME (cross-validation)

Heavy imports are LAZY — calling `make_backend("qutip")` must not import
qutip if you only want simqn, and vice versa.
"""
from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

from .base import BackendConfig, KeyProducer, RoundOutcome

if TYPE_CHECKING:
    from .base import KeyProducer  # noqa

log = logging.getLogger(__name__)


def make_backend(name: str, cfg: BackendConfig) -> KeyProducer:
    """Factory.  Raises ValueError on unknown name."""
    name = (name or "").lower()
    if name in ("qutip", "default"):
        from .qutip_backend import QuTiPBackend
        return QuTiPBackend(cfg)
    if name == "simqn":
        from .simqn_backend import SimQNBackend
        return SimQNBackend(cfg)
    if name == "sequence":
        from .sequence_backend import SeQUeNCeBackend
        return SeQUeNCeBackend(cfg)
    if name == "cvqkd":
        from .cvqkd_backend import CVQKDBackend
        return CVQKDBackend(cfg)
    if name in ("composite", "composite_sim_to_net"):
        from .composite_sim_to_net import CompositeBackend
        return CompositeBackend(cfg)
    if name in ("qkdnetsim_proxy", "qkdnetsim"):
        from .qkdnetsim_proxy import QKDNetSimProxyBackend
        return QKDNetSimProxyBackend(cfg)
    raise ValueError(f"unknown backend: {name!r}")


def resolve_default_backend_name() -> str:
    """Honour env var first, then YAML, then SimQN as final fallback."""
    env = os.environ.get("SIMULATOR_BACKEND")
    if env:
        return env
    from .. import config_loader
    return config_loader.get("simulator.backend", "simqn") or "simqn"


__all__ = ["KeyProducer", "BackendConfig", "RoundOutcome", "make_backend",
           "resolve_default_backend_name"]
