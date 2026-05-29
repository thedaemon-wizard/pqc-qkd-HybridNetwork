"""BB84 quantum key distribution simulation modules.

Modules:
    simulator      : Orchestrates one full BB84 round (Alice -> Channel -> Eve? -> Bob -> Sift -> Reconcile -> PA)
    alice          : Photon preparation (random bits + random bases in rectilinear/diagonal)
    bob            : Random-basis measurement
    eve            : Optional intercept-resend attacker
    reconciliation : Cascade error correction + Toeplitz privacy amplification

The simulator uses QuTiP only for the photon state objects; once measured we work in
classical numpy arrays for performance. This keeps each round O(N) instead of O(N*2^k).
"""
