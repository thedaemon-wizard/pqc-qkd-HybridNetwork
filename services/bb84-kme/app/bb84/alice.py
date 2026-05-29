"""Alice: prepares photons in random bits and random bases.

Bases:
    0 = rectilinear  ({|0>, |1>})           bit 0 -> |0>,  bit 1 -> |1>
    1 = diagonal     ({|+>, |->})           bit 0 -> |+>,  bit 1 -> |->

For the simulator we store only the (bit, basis) pair; the QuTiP state is reconstructed
on demand via `state_for(...)` to allow Eve/Bob to perform real quantum measurement.
"""
from __future__ import annotations

import numpy as np
import qutip as qt

# Pre-cached basis states (constructed once for performance)
_KET_0 = qt.basis(2, 0)
_KET_1 = qt.basis(2, 1)
_KET_P = (qt.basis(2, 0) + qt.basis(2, 1)).unit()   # |+>
_KET_M = (qt.basis(2, 0) - qt.basis(2, 1)).unit()   # |->


def prepare(n: int, rng: np.random.Generator | None = None) -> tuple[np.ndarray, np.ndarray]:
    """Sample `n` random bits and bases. Returns (bits, bases) both shape (n,) uint8."""
    rng = rng or np.random.default_rng()
    bits = rng.integers(0, 2, size=n, dtype=np.uint8)
    bases = rng.integers(0, 2, size=n, dtype=np.uint8)
    return bits, bases


def state_for(bit: int, basis: int) -> qt.Qobj:
    """Construct the QuTiP qubit state corresponding to (bit, basis)."""
    if basis == 0:
        return _KET_0 if bit == 0 else _KET_1
    return _KET_P if bit == 0 else _KET_M
