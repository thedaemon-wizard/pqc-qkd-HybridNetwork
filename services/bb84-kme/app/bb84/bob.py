"""Bob: measures incoming photons in randomly chosen bases.

The measurement uses QuTiP projective operators in either rectilinear or diagonal basis.
For the diagonal basis we apply a Hadamard rotation then measure in computational basis
(this is equivalent to projecting onto |+> / |->).
"""
from __future__ import annotations

import numpy as np
import qutip as qt

_H = qt.Qobj([[1, 1], [1, -1]]) / np.sqrt(2)
_P0 = qt.basis(2, 0) * qt.basis(2, 0).dag()   # |0><0|
_P1 = qt.basis(2, 1) * qt.basis(2, 1).dag()   # |1><1|


def random_bases(n: int, rng: np.random.Generator | None = None) -> np.ndarray:
    rng = rng or np.random.default_rng()
    return rng.integers(0, 2, size=n, dtype=np.uint8)


def measure(state: qt.Qobj, basis: int, rng: np.random.Generator | None = None) -> int:
    """Measure `state` in basis `basis` (0=Z, 1=X). Returns the classical bit outcome."""
    rng = rng or np.random.default_rng()
    if basis == 1:
        state = _H * state            # rotate to measure in X basis
    # QuTiP 5.x: <bra|·|ket> returns a complex; older versions return a 1x1 Qobj.
    amp = qt.basis(2, 0).dag() * state
    amp_val = amp if isinstance(amp, complex) else amp.full()[0, 0]
    p0 = float(abs(amp_val) ** 2)
    return 0 if rng.random() < p0 else 1
