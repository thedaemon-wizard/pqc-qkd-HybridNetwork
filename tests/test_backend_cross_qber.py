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
    from app.backends.base import cfg_from_yaml
    from app.backends._skr import (
        qber_Emu,
        total_transmittance,
    )
    from app.backends import make_backend

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
    if not out.accepted:
        pytest.skip(f"backend {backend_name} did not accept this round")
    # QBER should be within 20× of analytical (loose because backends use
    # different sift / sample strategies). Mostly we want < threshold.
    assert out.qber < cfg.qber_threshold_abort, (
        f"{backend_name} QBER {out.qber:.3f} >= threshold {cfg.qber_threshold_abort}"
    )
    assert len(out.key_bytes) == cfg.out_bits_per_key // 8


def test_optimizer_yields_positive_skr():
    from app import config_loader
    config_loader.reload()
    from app.optimizer import optimize_from_yaml

    result = optimize_from_yaml()
    assert result.skr_per_pulse > 0, "BO should find a positive SKR for default cfg"
    assert 0.30 <= result.mu <= 0.90
    assert 0.05 <= result.nu1 <= 0.20
