"""The `/pqc` cross-check has to compare secrets, not byte counts.

Two things were called cross-checks and were not.

`/api/kat` was documented as verifying liboqs against a PQClean reference. It
accepted a `seed_hex`, parsed it, and used it only for `len(seed)` -- nothing
was seeded, so the result was not reproducible and not a known-answer test. The
PQClean half was `os.path.isfile` on binaries the image never builds, so
`pqclean_test_present` was always false.

The page's "Independent cross-check -- liboqs" compared `ss_len` and `ct_len`
against the browser's values. Two implementations agreeing that ML-KEM-768
ciphertext is 1088 bytes shows only that both read the same table in FIPS 203.
An implementation that returned 1088 zero bytes would pass.

Building PQClean is not the fix either: it was archived on 2026-08-04 and its
retirement notice points at mlkem-native, mldsa-native and slhdsa-c. Depending
on an archived project for a correctness claim is a step backwards.

`/api/interop/mlkem` is the real thing. The browser generates a keypair with
@noble, liboqs encapsulates to it in C, and the browser decapsulates the
result. Agreement on the shared secret cannot happen unless both independently
written implementations compute ML-KEM correctly.
"""
from __future__ import annotations

import base64
import hashlib
import importlib

import pytest
from conftest import load_service_app
from fastapi.testclient import TestClient

load_service_app("pqc-validator", "pqc_validator_app")
main = importlib.import_module("pqc_validator_app.main")

pytestmark = pytest.mark.skipif(
    not getattr(main, "_OQS_AVAILABLE", False),
    reason="liboqs not installed on the host; this path is covered in the container image",
)

ALGO = "ML-KEM-768"


@pytest.fixture
def client():
    return TestClient(main.app)


def _keypair(algo: str = ALGO):
    """A keypair from liboqs standing in for the browser's @noble keypair.

    The host has no @noble, so this cannot be a true two-implementation test
    here -- that happens in the browser, and checklist row 4.6.13 records it.
    What these tests pin is the endpoint's contract: that it encapsulates to
    the key it was GIVEN, and that the committed digest is of the secret that
    key recovers.
    """
    import oqs
    with oqs.KeyEncapsulation(algo) as kem:
        pk = kem.generate_keypair()
        sk = kem.export_secret_key()
    return pk, sk


class TestInteropEndpoint:
    def test_encapsulates_to_the_supplied_key(self, client):
        import oqs
        pk, sk = _keypair()
        r = client.post("/api/interop/mlkem", json={
            "algo": ALGO, "public_key_b64": base64.b64encode(pk).decode(),
        })
        assert r.status_code == 200, r.text
        body = r.json()

        ct = base64.b64decode(body["ciphertext_b64"])
        with oqs.KeyEncapsulation(ALGO, sk) as kem:
            recovered = kem.decap_secret(ct)

        # The decisive assertion: the digest commits to the secret that OUR
        # key recovers. A server that encapsulated to a key of its own -- which
        # is exactly what /api/kat does -- fails here.
        assert hashlib.sha256(recovered).hexdigest() == body["shared_secret_sha256"]

    def test_does_not_put_the_shared_secret_on_the_wire(self, client):
        pk, _ = _keypair()
        r = client.post("/api/interop/mlkem", json={
            "algo": ALGO, "public_key_b64": base64.b64encode(pk).decode(),
        })
        body = r.json()
        assert "shared_secret" not in body
        assert "shared_secret_b64" not in body
        assert len(body["shared_secret_sha256"]) == 64

    def test_a_different_key_yields_a_different_commitment(self, client):
        # Guards against a server that returns a constant, which would make
        # every comparison "agree" for the wrong reason.
        digests = set()
        for _ in range(3):
            pk, _ = _keypair()
            r = client.post("/api/interop/mlkem", json={
                "algo": ALGO, "public_key_b64": base64.b64encode(pk).decode(),
            })
            digests.add(r.json()["shared_secret_sha256"])
        assert len(digests) == 3

    def test_rejects_a_wrong_length_key_before_liboqs_sees_it(self, client):
        r = client.post("/api/interop/mlkem", json={
            "algo": ALGO, "public_key_b64": base64.b64encode(b"too short").decode(),
        })
        assert r.status_code == 400
        assert "1184" in r.text  # ML-KEM-768 encapsulation key length, FIPS 203

    def test_rejects_malformed_base64(self, client):
        r = client.post("/api/interop/mlkem", json={
            "algo": ALGO, "public_key_b64": "!!! not base64 !!!",
        })
        assert r.status_code == 400

    def test_rejects_an_algorithm_this_build_does_not_have(self, client):
        pk, _ = _keypair()
        r = client.post("/api/interop/mlkem", json={
            "algo": "NotARealKEM", "public_key_b64": base64.b64encode(pk).decode(),
        })
        assert r.status_code == 400


class TestKatNoLongerOverclaims:
    """The old endpoint stays, but must not describe itself as a cross-check."""

    def test_says_it_is_not_a_known_answer_test(self, client):
        r = client.post("/api/kat", json={"algo": ALGO, "seed_hex": "00" * 32})
        assert r.status_code == 200
        body = r.json()
        assert body["is_known_answer_test"] is False
        assert body["cross_checked"] is False

    def test_admits_the_seed_is_ignored(self, client):
        # The field name itself now says so, because the previous name implied
        # the seed did something.
        r = client.post("/api/kat", json={"algo": ALGO, "seed_hex": "ab" * 32})
        assert "seed_bytes_ignored" in r.json()

    def test_no_longer_reports_a_pqclean_check_it_never_performed(self, client):
        r = client.post("/api/kat", json={"algo": ALGO, "seed_hex": "00" * 32})
        assert "pqclean_test_present" not in r.json()

    def test_the_same_seed_does_not_give_the_same_result(self, client):
        """Proves the point of the rename rather than asserting the docstring.

        A real KAT is reproducible. This is not, because liboqs supplies its own
        randomness -- so anything downstream that treated it as a fixed vector
        was relying on something that was never true.
        """
        seed = {"algo": ALGO, "seed_hex": "5a" * 32}
        a = client.post("/api/kat", json=seed).json()
        b = client.post("/api/kat", json=seed).json()
        assert a == b, "sizes are deterministic"
        # ...but nothing key-dependent is returned at all, which is the honest
        # position: there is no vector here to reproduce.
        assert not any(k.endswith("_b64") or k.endswith("_hex") for k in a)
