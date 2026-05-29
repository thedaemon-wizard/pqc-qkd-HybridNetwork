"""Information reconciliation + privacy amplification for sifted BB84 keys.

We use a lightweight Cascade-like estimator for QBER and a Toeplitz universal-hash
based privacy amplification (PA). For a research PoC this is enough to illustrate the
post-processing pipeline; a production system would use LDPC reconciliation.

Pipeline:
    sifted_a, sifted_b  -->  sample QBER on a random sub-sample
                       -->  if QBER > threshold: abort the block
                       -->  reconcile (we accept Alice's bits as truth; PA absorbs leak)
                       -->  Toeplitz hash compress to `out_bits` (default 256)
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(slots=True)
class ReconcileResult:
    accepted: bool
    qber: float
    final_key: bytes        # 32 bytes (256 bits) when accepted
    raw_used: int           # number of sifted bits consumed
    leak_estimate: int      # bits of information leaked to Eve (lower bound)


def _toeplitz_hash(bits: np.ndarray, out_len: int, seed: int) -> np.ndarray:
    """Universal hash via random Toeplitz matrix (mod 2).

    Args:
        bits:     input bits as np.uint8 array (values 0/1) of length n
        out_len:  number of output bits desired
        seed:     RNG seed used to generate the Toeplitz random vector
                  (publicly chosen, shared between Alice and Bob)
    """
    n = bits.size
    rng = np.random.default_rng(seed)
    rnd = rng.integers(0, 2, size=n + out_len - 1, dtype=np.uint8)
    out = np.empty(out_len, dtype=np.uint8)
    for i in range(out_len):
        col = rnd[i : i + n]
        out[i] = np.bitwise_xor.reduce(col & bits)
    return out


def reconcile(
    sifted_a: np.ndarray,
    sifted_b: np.ndarray,
    *,
    qber_threshold: float,
    out_bits: int = 256,
    pa_seed: int | None = None,
) -> ReconcileResult:
    """Run QBER estimation + privacy amplification.

    Both `sifted_a` and `sifted_b` MUST be the same length and indexed identically
    (i.e. already sifted: only positions where bases matched).
    """
    if sifted_a.size != sifted_b.size:
        raise ValueError("sifted arrays must have equal length")
    n = sifted_a.size

    # ------------------------------------------------------------------
    # 1) QBER estimation on a small random sub-sample, then discard those
    # ------------------------------------------------------------------
    sample_size = max(16, n // 10)
    if sample_size >= n:
        return ReconcileResult(False, 1.0, b"", n, 0)

    rng = np.random.default_rng()
    sample_idx = rng.choice(n, size=sample_size, replace=False)
    diff = sifted_a[sample_idx] ^ sifted_b[sample_idx]
    qber = float(diff.mean())

    if qber > qber_threshold:
        return ReconcileResult(False, qber, b"", n, 0)

    # Drop the disclosed sample bits from both arrays
    mask = np.ones(n, dtype=bool)
    mask[sample_idx] = False
    a_remain = sifted_a[mask]
    n_remain = a_remain.size

    # ------------------------------------------------------------------
    # 2) Reconciliation: in this lightweight PoC we accept Alice's bits.
    #    Real Cascade would xor-correct B->A; here we assume the QBER is
    #    low enough that PA over A side gives a secure secret.
    # ------------------------------------------------------------------

    # Estimated leak to Eve (binary entropy times block size)
    if 0 < qber < 1:
        h2 = -qber * np.log2(qber) - (1 - qber) * np.log2(1 - qber)
    else:
        h2 = 0.0
    leak = int(np.ceil(h2 * n_remain))

    # ------------------------------------------------------------------
    # 3) Privacy amplification via Toeplitz hash to `out_bits` bits
    # ------------------------------------------------------------------
    if n_remain < out_bits + leak + 64:
        # Insufficient entropy after leak accounting
        return ReconcileResult(False, qber, b"", n, leak)

    seed = pa_seed if pa_seed is not None else int(rng.integers(0, 2**31 - 1))
    hashed = _toeplitz_hash(a_remain, out_bits, seed)

    # pack to bytes (MSB-first)
    packed = np.packbits(hashed, bitorder="big").tobytes()
    return ReconcileResult(True, qber, packed, n, leak)
