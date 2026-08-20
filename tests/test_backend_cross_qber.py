"""Backend cross-validation: same physical params → same physical QBER.

QuTiP backend and SimQN backend each have their own photonic model.  When fed
the *same* BackendConfig (link length, detector efficiency, dark count,
intensity) the resulting QBER must agree within a tolerance set by the
analytical Lo-Ma formula.

This test is the canonical guard against backend drift.
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "bb84-kme"))
os.environ.setdefault("QKD_PARAMS_FILE", str(ROOT / "config" / "qkd_params.yaml"))


@pytest.mark.parametrize("backend_name", ["qutip", "simqn"])
def test_backend_keys_match_lo_ma_qber(backend_name):
    from app import config_loader
    config_loader.reload()
    from app.backends import make_backend
    from app.backends._skr import (
        qber_Emu,
        total_transmittance,
    )
    from app.backends.base import cfg_from_yaml

    cfg = cfg_from_yaml()
    try:
        backend = make_backend(backend_name, cfg)
    except RuntimeError as e:
        pytest.skip(f"{backend_name} not available: {e}")

    eta = total_transmittance(
        cfg.detector_efficiency,
        cfg.fiber_attenuation_db_per_km,
        cfg.link_length_km,
    )
    Y0 = cfg.dark_count_rate_hz / max(cfg.pulse_rate_hz, 1.0)
    expected_qber = qber_Emu(Y0, eta, cfg.misalignment_error_ed,
                              cfg.intensity_signal_mu)

    out = asyncio.run(backend.run_round())

    # A round the backend rejected used to be skipped, which meant a backend
    # that rejected EVERY round still reported a green test. Rejection is a
    # real outcome and must be asserted on: it is only legitimate when the
    # observed QBER is at or above the abort threshold.
    if not out.accepted:
        assert out.qber >= cfg.qber_threshold_abort, (
            f"{backend_name} rejected a round at QBER {out.qber:.4f}, "
            f"below the abort threshold {cfg.qber_threshold_abort}"
        )
        return

    assert out.qber < cfg.qber_threshold_abort, (
        f"{backend_name} QBER {out.qber:.3f} >= threshold {cfg.qber_threshold_abort}"
    )
    assert len(out.key_bytes) == cfg.out_bits_per_key // 8

    # The actual cross-validation this test is named for. `expected_qber` was
    # computed and then never used, so the analytical comparison -- the whole
    # point -- never happened.
    #
    # The tolerance is deliberately wide: backends differ in sifting and
    # sampling strategy, and a Monte-Carlo QBER estimated from a finite block
    # fluctuates. What this catches is an order-of-magnitude divergence from
    # the Lo-Ma channel model, which is the failure mode that matters.
    assert out.qber == pytest.approx(expected_qber, abs=0.05), (
        f"{backend_name} QBER {out.qber:.4f} diverges from the analytical "
        f"Lo-Ma value {expected_qber:.4f} (eta={eta:.3e}, Y0={Y0:.3e})"
    )


def test_optimizer_beats_a_naive_intensity_choice():
    """The optimiser must actually improve on an arbitrary intensity.

    The previous version of this test asserted only `skr > 0` plus
    `0.30 <= mu <= 0.90` and `0.05 <= nu1 <= 0.20` -- which are exactly the
    optimiser's own search bounds, so they held no matter what it returned. It
    also called optimize_from_yaml(), running the production 50-call Bayesian
    search, which took ~94 s and made the whole suite unpleasant to run.

    This drives the deterministic closed-form scan instead: fast, seedless, and
    it checks the property that actually matters -- the chosen intensity beats
    a plausible naive one, and the reported SKR matches the shared key-rate
    model at those parameters.
    """
    from app import config_loader
    config_loader.reload()
    from app.backends._skr import skr_finite, total_transmittance
    from app.backends.base import cfg_from_yaml
    from app.optimizer import optimize_closed_form

    cfg = cfg_from_yaml()
    eta = total_transmittance(
        cfg.detector_efficiency, cfg.fiber_attenuation_db_per_km, cfg.link_length_km,
    )
    Y0 = cfg.dark_count_rate_hz / max(cfg.pulse_rate_hz, 1.0)
    fixed = {
        "eta_total": eta, "Y0": Y0, "e_d": cfg.misalignment_error_ed,
        "f_EC": cfg.ec_efficiency_f, "N": cfg.block_size_N,
        "eps": cfg.security_epsilon,
    }

    result = optimize_closed_form(**fixed)

    assert result.skr_per_pulse > 0, "no positive SKR found for the default config"
    assert result.n_calls > 1, "the scan evaluated only one point"

    # The reported optimum must agree with the shared key-rate model, not with
    # some private copy of it inside the optimiser.
    recomputed = skr_finite(
        mu=result.mu, nu1=result.nu1, nu2=result.nu2, **fixed,
    )
    assert result.skr_per_pulse == pytest.approx(recomputed, rel=1e-9), (
        "optimiser SKR disagrees with _skr.skr_finite at the same parameters"
    )

    # And it must beat a naive guess taken from the opposite end of the range.
    naive_mu = 0.9
    naive = skr_finite(mu=naive_mu, nu1=naive_mu / 5.0, nu2=0.0, **fixed)
    assert result.skr_per_pulse >= naive, (
        f"optimiser picked mu={result.mu:.2f} (SKR {result.skr_per_pulse:.3e}) "
        f"which is worse than a naive mu={naive_mu} (SKR {naive:.3e})"
    )
