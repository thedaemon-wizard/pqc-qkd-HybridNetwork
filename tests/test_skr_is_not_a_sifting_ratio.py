"""Every backend's `skr_bps` must be a secret-key rate, not a sifting fraction.

All three backends previously derived it a different way, and none of them
computed a secret-key rate:

    qutip            n_sifted / n_photons * pulse_rate     sifting fraction
    simqn            sifted / batch_size  * pulse_rate     sifting fraction
    qkdnetsim_proxy  pulse_rate / 2                        a constant

The sifting fraction is the proportion of pulses surviving basis
reconciliation. The secret-key rate is what survives error correction leaking
f_EC * h2(E_mu) and privacy amplification removing Eve's information -- always
strictly smaller, and on this configuration smaller by a factor of about 41.

Reporting the former in a field named `skr_bps` overstates the headline result
of the whole project, so this pins the relationship rather than the number:
whatever the parameters, the secret-key rate must sit strictly below the
sifting bound.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "bb84-kme"))
os.environ.setdefault("QKD_PARAMS_FILE", str(ROOT / "config" / "qkd_params.yaml"))


def _cfg():
    from app import config_loader
    config_loader.reload()
    from app.backends.base import cfg_from_yaml
    return cfg_from_yaml()


def test_skr_is_strictly_below_the_sifting_bound():
    """The property that distinguishes a key rate from a sifting ratio."""
    from app.backends._skr import skr_bps_from_config

    cfg = _cfg()
    skr = skr_bps_from_config(cfg)

    # BB84 sifts on matching bases, so at most half the pulses survive. Any
    # "rate" at or above this is a sifting figure wearing a key-rate label.
    sifting_bound = cfg.pulse_rate_hz * 0.5
    assert 0.0 < skr < sifting_bound, (
        f"skr_bps={skr:,.0f} is not below the sifting bound {sifting_bound:,.0f}; "
        "it is a sifting fraction, not a secret-key rate"
    )


def test_skr_matches_the_shared_model_exactly():
    """It must come from the golden-vector-tested model, not a private copy."""
    from app.backends._skr import (
        skr_bps_from_config,
        skr_finite,
        total_transmittance,
    )

    cfg = _cfg()
    eta = total_transmittance(
        cfg.detector_efficiency, cfg.fiber_attenuation_db_per_km, cfg.link_length_km,
    )
    expected = skr_finite(
        Y0=cfg.dark_count_rate_hz / max(cfg.pulse_rate_hz, 1.0),
        eta_total=eta, e_d=cfg.misalignment_error_ed,
        mu=cfg.intensity_signal_mu, nu1=cfg.intensity_decoy_1_nu1,
        nu2=cfg.intensity_decoy_2_nu2, f_EC=cfg.ec_efficiency_f,
        N=cfg.block_size_N, eps=cfg.security_epsilon,
    ) * cfg.pulse_rate_hz
    assert skr_bps_from_config(cfg) == pytest.approx(expected, rel=1e-12)


def test_skr_falls_as_the_link_gets_longer():
    """A sanity property a constant would fail.

    `qkdnetsim_proxy` returned `pulse_rate_hz / 2` regardless of the channel.
    Any figure that does not move with link length is not modelling anything.
    """
    from dataclasses import replace

    from app.backends._skr import skr_bps_from_config

    cfg = _cfg()
    near = skr_bps_from_config(replace(cfg, link_length_km=10.0))
    far = skr_bps_from_config(replace(cfg, link_length_km=80.0))
    assert near > far, f"SKR did not fall with distance: {near:,.0f} -> {far:,.0f}"


@pytest.mark.parametrize("backend_name", ["qutip", "simqn"])
def test_backend_reports_the_shared_rate(backend_name):
    """No backend may reintroduce its own derivation."""
    import asyncio

    from app.backends import make_backend
    from app.backends._skr import skr_bps_from_config

    cfg = _cfg()
    try:
        backend = make_backend(backend_name, cfg)
    except RuntimeError as e:
        pytest.skip(f"{backend_name} unavailable: {e}")

    out = asyncio.run(backend.run_round())
    assert out.skr_bps == pytest.approx(skr_bps_from_config(cfg), rel=1e-9), (
        f"{backend_name} computes skr_bps its own way again"
    )


def test_simqn_flags_synthesised_rounds():
    """A synthesised stream must not be indistinguishable from a measured one.

    SimQN falls back to generating a photon stream when it under-produces in
    the sampling window. That is defensible -- it is calibrated to the same
    configured physics -- but it is the DEFAULT backend, and presenting
    generated bits as a simulation result without saying so is how a demo
    starts reporting numbers nobody can reproduce.
    """
    import asyncio

    from app.backends import make_backend

    cfg = _cfg()
    try:
        backend = make_backend("simqn", cfg)
    except RuntimeError as e:
        pytest.skip(f"simqn unavailable: {e}")

    out = asyncio.run(backend.run_round())
    assert "synthetic" in out.backend_meta, (
        "backend_meta must say whether the stream was measured or synthesised"
    )
    assert isinstance(out.backend_meta["synthetic"], bool)
