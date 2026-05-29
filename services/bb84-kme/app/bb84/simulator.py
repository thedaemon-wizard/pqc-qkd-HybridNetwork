"""End-to-end BB84 round orchestrator.

A "round" produces zero or one 256-bit sifted key. It performs:
    1. Alice prepares N random (bit, basis) pairs
    2. (Optional) channel depolarizing noise applied
    3. (Optional) Eve intercept-resend at probability p
    4. Bob measures in random bases
    5. Public basis disclosure -> sifting
    6. QBER estimation + reconciliation + privacy amplification

Performance note: for N up to ~4096 photons this runs in ~50-200 ms per round on the
target machine (CPU only). The simulator is intentionally CPU-bound for portability.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

import numpy as np
import qutip as qt

from . import alice, bob, eve, reconciliation


@dataclass(slots=True)
class RoundConfig:
    n_photons: int = 2048
    channel_noise: float = 0.01          # bit-flip / depolarizing probability
    eve_enabled: bool = False
    eve_prob: float = 0.0                # P(intercept | eve_enabled)
    qber_threshold: float = 0.11
    out_bits: int = 256


@dataclass(slots=True)
class RoundResult:
    accepted: bool
    qber: float
    key_bytes: bytes
    n_photons: int
    n_sifted: int
    intercepted: int
    elapsed_ms: float
    sample_frames: list[dict] = field(default_factory=list)


def _maybe_flip(bit: int, p: float, rng: np.random.Generator) -> int:
    return bit ^ 1 if rng.random() < p else bit


def run_round(cfg: RoundConfig, *, rng: np.random.Generator | None = None) -> RoundResult:
    rng = rng or np.random.default_rng()
    t0 = time.perf_counter()

    bits_a, bases_a = alice.prepare(cfg.n_photons, rng)
    bases_b = bob.random_bases(cfg.n_photons, rng)

    raw_bob = np.zeros(cfg.n_photons, dtype=np.uint8)
    intercepted_count = 0
    frames: list[dict] = []
    # Sample a small number of frames for the WebUI animation
    frame_idx_set = set(rng.choice(cfg.n_photons, size=min(16, cfg.n_photons), replace=False).tolist())

    for i in range(cfg.n_photons):
        psi = alice.state_for(int(bits_a[i]), int(bases_a[i]))

        if cfg.eve_enabled and cfg.eve_prob > 0:
            psi, was_int = eve.maybe_attack(psi, cfg.eve_prob, rng)
            intercepted_count += int(was_int)

        b_meas = bob.measure(psi, int(bases_b[i]), rng=rng)
        # apply classical channel noise after measurement (simplified model)
        b_meas = _maybe_flip(b_meas, cfg.channel_noise, rng)
        raw_bob[i] = b_meas

        if i in frame_idx_set:
            frames.append(
                {
                    "i": i,
                    "alice_bit": int(bits_a[i]),
                    "alice_basis": int(bases_a[i]),
                    "bob_basis": int(bases_b[i]),
                    "bob_bit": int(b_meas),
                    "basis_match": bool(bases_a[i] == bases_b[i]),
                }
            )

    # ------------------- Sift -------------------
    sift_mask = bases_a == bases_b
    sifted_a = bits_a[sift_mask]
    sifted_b = raw_bob[sift_mask]

    rec = reconciliation.reconcile(
        sifted_a, sifted_b,
        qber_threshold=cfg.qber_threshold,
        out_bits=cfg.out_bits,
    )

    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    return RoundResult(
        accepted=rec.accepted,
        qber=rec.qber,
        key_bytes=rec.final_key,
        n_photons=cfg.n_photons,
        n_sifted=int(sifted_a.size),
        intercepted=intercepted_count,
        elapsed_ms=elapsed_ms,
        sample_frames=frames,
    )
