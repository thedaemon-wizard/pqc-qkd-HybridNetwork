"""Unit tests for the BB84 simulator (no networking needed)."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

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


def test_seeded_round_is_reproducible():
    """The same seed must give the same result.

    reconcile() used to build its own unseeded generator for the disclosed QBER
    sub-sample, so a caller passing default_rng(seed) still got a different
    answer every run. That made seeded tests flaky and silently defeated
    `simulator.rng_seed` in config/qkd_params.yaml.
    """
    cfg = RoundConfig(n_photons=1024, channel_noise=0.0, eve_enabled=True, eve_prob=1.0)
    runs = [run_round(cfg, rng=np.random.default_rng(7)) for _ in range(3)]
    assert len({r.qber for r in runs}) == 1, (
        f"same seed gave different QBERs: {[f'{r.qber:.4f}' for r in runs]}"
    )


def test_eve_drives_qber_to_the_intercept_resend_value():
    """Full intercept-resend must drive QBER to ~25%, and abort the round.

    Asserting the MEAN over several seeds rather than a single draw. The QBER
    is estimated from a disclosed sub-sample of only ~51 bits, so one round has
    a standard deviation of roughly 6 percentage points -- a single-seed
    threshold assertion is a coin flip dressed up as a test, and did in fact
    fail in CI on an unlucky draw.
    """
    cfg = RoundConfig(n_photons=1024, channel_noise=0.0, eve_enabled=True, eve_prob=1.0)
    results = [run_round(cfg, rng=np.random.default_rng(s)) for s in range(24)]
    qbers = [r.qber for r in results]
    mean_qber = sum(qbers) / len(qbers)

    # Theory: intercept-resend in a random basis corrupts half the sifted bits
    # half the time -> 0.25.
    assert mean_qber == pytest.approx(0.25, abs=0.04), (
        f"mean QBER {mean_qber:.3f} over {len(qbers)} seeds is not the "
        f"intercept-resend value 0.25 (min {min(qbers):.3f}, max {max(qbers):.3f})"
    )
    # Every round must be rejected: even the luckiest draw here sits above the
    # 11% abort threshold in practice, and accepting one would mean handing out
    # a key Eve holds.
    assert not any(r.accepted for r in results), (
        "a fully intercepted round was accepted"
    )


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
