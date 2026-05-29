"""Unit tests for the BB84 simulator (no networking needed)."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

# Make services/bb84-kme/app importable
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "bb84-kme"))

from app.bb84.simulator import RoundConfig, run_round  # noqa: E402


def test_no_eve_low_qber():
    # 2048 photons → ~1024 sifted → enough entropy after PA leak budget
    cfg = RoundConfig(n_photons=2048, channel_noise=0.0, eve_enabled=False)
    result = run_round(cfg, rng=np.random.default_rng(42))
    assert result.qber < 0.05
    assert result.accepted is True
    assert len(result.key_bytes) == 32


def test_eve_drives_qber_up():
    cfg = RoundConfig(n_photons=1024, channel_noise=0.0, eve_enabled=True, eve_prob=1.0)
    result = run_round(cfg, rng=np.random.default_rng(7))
    # Full intercept-resend should yield ~25% QBER theoretically (0.25)
    assert result.qber > 0.15, f"expected high QBER, got {result.qber:.3f}"
    assert result.accepted is False, "Reconciliation must abort above threshold"


def test_qutip_state_orthogonality():
    from app.bb84 import alice, bob
    # |0> measured in Z basis -> 0
    s = alice.state_for(0, 0)
    rng = np.random.default_rng(123)
    outcomes = [bob.measure(s, 0, rng=rng) for _ in range(50)]
    assert all(o == 0 for o in outcomes)
    # |+> measured in X basis -> 0 (since H|+> = |0>)
    s = alice.state_for(0, 1)
    outcomes = [bob.measure(s, 1, rng=rng) for _ in range(50)]
    assert all(o == 0 for o in outcomes)
