"""The agility matrix must contain somewhere to move TO.

`/verify` presents its matrix as "independent evidence" of crypto agility. It
listed ML-KEM-512/768/1024 and ML-DSA-44/65/87 -- six algorithms, every one of
them resting on module lattices. A structural break in that assumption takes
out the entire table at once.

That is parameter agility presented as algorithm agility. RFC 7696 is about
being able to move; the point is having a destination that fails independently.

SLH-DSA (FIPS 205) is hash-based and is that destination. The pinned liboqs
exposes 156 SLH-DSA mechanisms, so the omission was a default list, not a
capability gap.

The browser side already had this -- `src/lib/sim/pqcAgility.test.ts` asserts
two families across seven signature schemes. Only the server matrix, which is
the one `/verify` renders and calls evidence, did not.

Naming trap worth keeping: liboqs spells it `SLH_DSA_PURE_SHA2_128S` and
@noble spells it `SLH-DSA-SHA2-128s`. Passing the browser's spelling to liboqs
does not raise -- the row simply comes back `enabled: false`, so a silent
downgrade to one family would look like a working matrix.
"""
from __future__ import annotations

import importlib

import pytest
from conftest import load_service_app

load_service_app("pqc-validator", "pqc_validator_app")
main = importlib.import_module("pqc_validator_app.main")

pytestmark = pytest.mark.skipif(
    not getattr(main, "_OQS_AVAILABLE", False),
    reason="liboqs not installed on the host; this runs inside the pqc-validator image",
)

# FIPS 205 Table 2. Taken from the standard, not from running the code -- the
# same values `pqcAgility.test.ts` pins for the browser, so agreement here is a
# cross-implementation check as well as a size check.
FIPS_205_SIG_LEN = {
    "SLH_DSA_PURE_SHA2_128S": 7856,
    "SLH_DSA_PURE_SHA2_192S": 16224,
    "SLH_DSA_PURE_SHA2_256S": 29792,
}


def _families(algos) -> set[str]:
    return {"hash-based" if "SLH" in a else "module-lattice" for a in algos}


def test_the_default_signature_list_is_not_one_family():
    fams = _families(main.DEFAULT_SIG_ALGOS)
    assert len(fams) >= 2, (
        f"DEFAULT_SIG_ALGOS covers only {fams}. A matrix whose every entry rests "
        "on one hardness assumption shows parameter agility, not algorithm "
        "agility -- one break takes the whole table."
    )
    assert "hash-based" in fams


def test_every_default_algorithm_is_actually_enabled_in_this_liboqs():
    """A misspelled name comes back `enabled: false` rather than raising.

    That is the failure mode that would silently return the matrix to one
    family while still rendering as a table of results.
    """
    import oqs

    enabled = set(oqs.get_enabled_sig_mechanisms())
    missing = [a for a in main.DEFAULT_SIG_ALGOS if a not in enabled]
    assert not missing, (
        f"these default signature algorithms are not enabled in the pinned "
        f"liboqs: {missing}. Check the spelling -- liboqs uses "
        "SLH_DSA_PURE_SHA2_128S, not the browser's SLH-DSA-SHA2-128s."
    )


@pytest.mark.parametrize("algo,expected", sorted(FIPS_205_SIG_LEN.items()))
def test_slh_dsa_signature_sizes_match_fips_205(algo, expected):
    """Round-trip success proves nothing about WHICH algorithm you got."""
    import oqs

    with oqs.Signature(algo) as s:
        pk = s.generate_keypair()
        sig = s.sign(b"agility matrix size check")
        assert s.verify(b"agility matrix size check", sig, pk)
    assert len(sig) == expected, (
        f"{algo} signature is {len(sig)} B, FIPS 205 Table 2 says {expected} B"
    )


def test_the_size_cost_of_leaving_the_lattice_is_visible():
    """Not incidental: it is why a deployment cannot simply default to the
    safer assumption, and the matrix should make it apparent."""
    import oqs

    with oqs.Signature("ML-DSA-65") as s:
        s.generate_keypair()
        lattice = len(s.sign(b"x"))
    with oqs.Signature("SLH_DSA_PURE_SHA2_192S") as s:
        s.generate_keypair()
        hash_based = len(s.sign(b"x"))
    assert hash_based > 4 * lattice, (
        f"expected the hash-based signature to be far larger; got {hash_based} B "
        f"against {lattice} B"
    )
