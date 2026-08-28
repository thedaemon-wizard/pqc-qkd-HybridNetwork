"""ML-KEM known-answer tests: NIST's vector, plus cross-implementation agreement.

Two kinds of check, and the difference matters.

The NIST ACVP vector is authoritative -- it is NIST's own published expected
output, so it catches an implementation that is wrong. Everything else here
compares liboqs against @noble, which catches disagreement but could not catch
both being wrong in the same way.

The browser half lives in
`services/webui-frontend/src/lib/sim/mlkemKat.test.ts` and pins the SAME
digests. Neither file is authoritative on its own: the digests are legitimate
only because a C implementation and a JavaScript implementation, written by
different authors, independently produced identical bytes from the same seed.

That distinction is the whole point. This project had no KAT -- `/api/kat` was
named one but seeded nothing -- and the tempting fix was to record what the
code produces and assert it forever. A vector taken from the implementation
under test cannot detect a consistently wrong implementation; it only detects
change. Two independent implementations agreeing is evidence about FIPS 203.

ML-KEM key generation is deterministic given the 64-byte seed (FIPS 203
`ML-KEM.KeyGen_internal`, seed = d || z), so agreement requires both to match
the standard on seed ordering, matrix expansion and encapsulation-key encoding.

Requires liboqs, so it runs inside the pqc-validator image in CI rather than on
the host. If it silently skipped in both places it would be decorative.
"""
from __future__ import annotations

import hashlib
import importlib

import pytest
from conftest import load_service_app

load_service_app("pqc-validator", "pqc_validator_app")
main = importlib.import_module("pqc_validator_app.main")

pytestmark = pytest.mark.skipif(
    not getattr(main, "_OQS_AVAILABLE", False),
    reason="liboqs not installed on the host; this runs inside the pqc-validator image",
)

SEED_BYTE = 0x01

# NIST ACVP, ML-KEM-768 key generation -- the authoritative vector, from NIST's
# own validation suite rather than from any implementation here.
#
#   usnistgov/ACVP-Server, gen-val/json-files/ML-KEM-keyGen-FIPS203/
#   internalProjection.json @ 15c0f3deeefbfa8cb6cd32a99e1ca3b738c66bf0
#   testGroups[1].tests[0]  -- parameterSet ML-KEM-768, tgId 2, tcId 26
#
# ACVP gives d and z separately; FIPS 203 Algorithm 16 takes them as the
# ordered pair KeyGen_internal(d, z), and the 64-byte d || z packing is an
# implementation convention that both liboqs and @noble follow.
ACVP_D = "e582b7d75e6c80b05ae392a1fc9f7153b12390fd99930368cc67a768baebc8a0"
ACVP_Z = "1cdacb8740c0b87c4a379575f187b367cbfa3b300bf591b109f79816e9cbe8f0"
ACVP_EK_SHA256 = "4158f6afb5e516c99f1da07da8c651348422b17c1f4e9a08ad73fb1f91249b3e"

# Cross-derived 2026-08-22 by liboqs (this file) and @noble/post-quantum 0.7.0
# (the browser test).
#
# Public-key lengths are FIPS 203 **Table 3**, "Sizes (in bytes) of keys and
# ciphertexts of ML-KEM" -- not Table 2, which is "Approved parameter sets"
# (n, q, k, eta1, eta2, du, dv, required RBG strength) and states no byte
# length at all. FIPS 203 introduces it that way itself: "The values of these
# variables in each parameter set are given in Table 2 of Section 8." The
# standard calls this key the encapsulation key; 800 / 1184 / 1568 is its row
# in Table 3.
CROSS_DERIVED = [
    ("ML-KEM-512", 800,
     "871c0a93974ea840f32bf4fd4352e37a5e2422815e0f43f73f6acd4895b93e37"),
    ("ML-KEM-768", 1184,
     "e68d60857f9cb41f88c278ca430e472c6df5679fd5bac3ce872334293c5d0c42"),
    ("ML-KEM-1024", 1568,
     "05227acb49aefea81141d2bbc32ed84178283517d724ebc04d570ce84725f656"),
]


def _seeded_public_key(algo: str) -> bytes:
    import oqs
    kem = oqs.KeyEncapsulation(algo)
    try:
        seed = bytes([SEED_BYTE]) * kem.length_keypair_seed
        return kem.generate_keypair_seed(seed)
    finally:
        kem.free()


def test_matches_the_nist_acvp_vector():
    """The authoritative check: NIST's own published expected output.

    Everything else in this file compares two implementations to each other,
    which catches disagreement but could not catch both being wrong in the same
    way. This compares against NIST.
    """
    import oqs
    kem = oqs.KeyEncapsulation("ML-KEM-768")
    try:
        pk = kem.generate_keypair_seed(bytes.fromhex(ACVP_D + ACVP_Z))
    finally:
        kem.free()
    assert len(pk) == 1184
    assert hashlib.sha256(pk).hexdigest() == ACVP_EK_SHA256


def test_the_acvp_seed_ordering_is_d_then_z():
    """d || z, not z || d.

    The packing is convention rather than spec, so this is the one detail that
    could be wrong while every length and format still looked right. Asserting
    the reversed order FAILS is what pins it.
    """
    import oqs
    kem = oqs.KeyEncapsulation("ML-KEM-768")
    try:
        reversed_pk = kem.generate_keypair_seed(bytes.fromhex(ACVP_Z + ACVP_D))
    finally:
        kem.free()
    assert hashlib.sha256(reversed_pk).hexdigest() != ACVP_EK_SHA256


@pytest.mark.parametrize(("algo", "pk_len", "sha256"), CROSS_DERIVED)
def test_seeded_key_matches_the_cross_derived_vector(algo, pk_len, sha256):
    pk = _seeded_public_key(algo)
    assert len(pk) == pk_len
    assert hashlib.sha256(pk).hexdigest() == sha256, (
        f"{algo} encapsulation key changed. Before updating this vector, "
        "recompute it from BOTH implementations and confirm they still agree. "
        "Taking the new digest from whichever side changed turns this back "
        "into a self-check."
    )


def test_the_seed_length_is_the_one_the_vector_assumes():
    """FIPS 203 seeds keygen with d || z, 64 bytes.

    Pinned because the vector is meaningless if liboqs ever wants a different
    seed size -- the digests would still be reproducible here and would no
    longer describe the same computation as the browser side.
    """
    import oqs
    for algo, _, _ in CROSS_DERIVED:
        kem = oqs.KeyEncapsulation(algo)
        try:
            assert kem.length_keypair_seed == 64, f"{algo} seed length changed"
        finally:
            kem.free()


def test_generation_is_deterministic():
    a = _seeded_public_key("ML-KEM-768")
    b = _seeded_public_key("ML-KEM-768")
    assert a == b


def test_a_different_seed_gives_a_different_key():
    """Guards against an implementation that ignores the seed.

    Exactly the failure `/api/kat` had: it accepted a seed, parsed it and threw
    it away. Every seeded assertion above would pass for the wrong reason.
    """
    import oqs
    kem = oqs.KeyEncapsulation("ML-KEM-768")
    try:
        n = kem.length_keypair_seed
        one = kem.generate_keypair_seed(bytes([0x01]) * n)
    finally:
        kem.free()
    kem2 = oqs.KeyEncapsulation("ML-KEM-768")
    try:
        two = kem2.generate_keypair_seed(bytes([0x02]) * n)
    finally:
        kem2.free()
    assert one != two


def test_every_parameter_set_has_a_distinct_vector():
    """A mis-transcribed table row would otherwise pin the wrong algorithm."""
    digests = {sha for _, _, sha in CROSS_DERIVED}
    lengths = {ln for _, ln, _ in CROSS_DERIVED}
    assert len(digests) == len(CROSS_DERIVED)
    assert len(lengths) == len(CROSS_DERIVED)
