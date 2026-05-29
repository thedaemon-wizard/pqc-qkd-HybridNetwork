"""Eve: optional intercept-resend attacker.

When enabled with probability `p_intercept`, Eve:
    1. Picks a random basis
    2. Measures the photon (collapsing its state)
    3. Re-prepares a fresh photon in her measurement basis from her result
    4. Forwards it to Bob

This is the canonical attack that introduces ~25% QBER on intercepted positions.
"""
from __future__ import annotations

import numpy as np
import qutip as qt

from . import alice, bob


def maybe_attack(
    state: qt.Qobj,
    p_intercept: float,
    rng: np.random.Generator | None = None,
) -> tuple[qt.Qobj, bool]:
    """Possibly intercept-resend.

    Returns (possibly-tampered-state, was_intercepted_flag).
    """
    rng = rng or np.random.default_rng()
    if rng.random() >= p_intercept:
        return state, False

    eve_basis = int(rng.integers(0, 2))
    bit = bob.measure(state, eve_basis, rng=rng)
    new_state = alice.state_for(bit, eve_basis)
    return new_state, True
