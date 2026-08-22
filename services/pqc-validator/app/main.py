"""PQC implementation cross-validator.

Cross-implementation evidence for ML-KEM: the browser generates a keypair
with @noble, liboqs encapsulates to it here in C, and the browser decapsulates.
Agreement on the shared secret is only possible if two independently written
implementations both follow FIPS 203. See `/api/interop/mlkem`.

This module once claimed to compare liboqs against PQClean and verify
byte-equality. It never did -- the "check" was `os.path.isfile` on binaries the
image does not build -- and PQClean was archived on 2026-08-04.

Endpoints:
    GET  /health
    GET  /api/algorithms          list supported KEMs / signatures
    POST /api/kat                 {algo, seed_hex} -> roundtrip + comparison
    POST /api/roundtrip           {algo} -> single keygen/encap/decap with both libs
"""
from __future__ import annotations

import base64
import hashlib
import logging
import os
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
log = logging.getLogger("pqc-validator")


try:
    import oqs  # liboqs-python
    _OQS_AVAILABLE = True
except Exception as e:    # pragma: no cover (env)
    log.warning("liboqs-python not importable: %s", e)
    _OQS_AVAILABLE = False


app = FastAPI(title="PQC Validator", version="0.1.0")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "oqs": str(_OQS_AVAILABLE)}


@app.get("/api/algorithms")
async def algorithms() -> dict[str, Any]:
    if not _OQS_AVAILABLE:
        raise HTTPException(503, "liboqs not available")
    kems = list(oqs.get_enabled_kem_mechanisms())
    sigs = list(oqs.get_enabled_sig_mechanisms())
    return {
        "liboqs": {"kems": kems[:32], "sigs": sigs[:32]},
        # No "pqclean" key: the directory's presence never implied a
        # comparison, and reporting it invited the reading that one happened.
    }


class RoundtripRequest(BaseModel):
    algo: str = "ML-KEM-768"


@app.post("/api/roundtrip")
async def roundtrip(req: RoundtripRequest) -> dict[str, Any]:
    """Run an encap/decap roundtrip through liboqs and verify
    self-consistency (ct/pk/ss roundtrip succeeds and ss matches)."""
    if not _OQS_AVAILABLE:
        raise HTTPException(503, "liboqs not available")
    if req.algo not in oqs.get_enabled_kem_mechanisms():
        raise HTTPException(400, f"unsupported algorithm: {req.algo}")
    try:
        with oqs.KeyEncapsulation(req.algo) as kem:
            pk = kem.generate_keypair()
            ct, ss_a = kem.encap_secret(pk)
            ss_b = kem.decap_secret(ct)
    except Exception as e:
        raise HTTPException(500, f"liboqs failure: {e}")
    return {
        "algo": req.algo,
        "pk_len": len(pk),
        "ct_len": len(ct),
        "ss_len": len(ss_a),
        "ss_match": ss_a == ss_b,
        "library": "liboqs",
    }


# Default crypto-agility matrix: NIST-standard ML-KEM (encap/decap) + ML-DSA
# (sign/verify) across all security levels. Swapping algorithms = one list edit.
DEFAULT_KEM_ALGOS = ["ML-KEM-512", "ML-KEM-768", "ML-KEM-1024"]

# Signatures span TWO mathematical families on purpose.
#
# The matrix was ML-DSA only. Every entry in it -- and every KEM above -- rests
# on module lattices, so a structural break in that assumption takes out the
# whole table at once. A matrix like that demonstrates parameter agility, not
# algorithm agility, and RFC 7696 is about having somewhere to move TO.
#
# SLH-DSA (FIPS 205) is hash-based and is that somewhere. The pinned liboqs
# exposes 156 SLH-DSA mechanisms; three suffice to cover NIST categories 1, 3
# and 5.
#
# Note the naming: liboqs uses SLH_DSA_PURE_SHA2_128S while the browser side
# (@noble, src/lib/sim/pqc.ts) uses SLH-DSA-SHA2-128s. Same algorithm, two
# spellings, and passing the browser's spelling here silently disables the row
# rather than erroring -- `enabled` would simply read false.
DEFAULT_SIG_ALGOS = [
    "ML-DSA-44", "ML-DSA-65", "ML-DSA-87",
    "SLH_DSA_PURE_SHA2_128S", "SLH_DSA_PURE_SHA2_192S", "SLH_DSA_PURE_SHA2_256S",
]


class AgilityRequest(BaseModel):
    kems: list[str] | None = None
    sigs: list[str] | None = None




@app.post("/api/agility")
async def agility(req: AgilityRequest | None = None) -> dict[str, Any]:
    """Crypto-agility evidence: exercise a matrix of liboqs algorithms and
    report pass/fail per algorithm.

    Covers ML-KEM encap/decap plus ML-DSA and SLH-DSA sign/verify -- two
    signature families, so the table survives a structural break in either.
    Reporting only module-lattice schemes would have shown parameter agility
    while calling it algorithm agility.

    No PQClean field is returned; the response never carried one, and this
    docstring used to say it did."""
    if not _OQS_AVAILABLE:
        raise HTTPException(503, "liboqs not available")
    kem_algos = (req.kems if req and req.kems else DEFAULT_KEM_ALGOS)
    sig_algos = (req.sigs if req and req.sigs else DEFAULT_SIG_ALGOS)
    enabled_kems = set(oqs.get_enabled_kem_mechanisms())
    enabled_sigs = set(oqs.get_enabled_sig_mechanisms())
    matrix: list[dict[str, Any]] = []

    for a in kem_algos:
        row: dict[str, Any] = {"algo": a, "family": "KEM", "enabled": a in enabled_kems}
        if a in enabled_kems:
            try:
                with oqs.KeyEncapsulation(a) as kem:
                    pk = kem.generate_keypair()
                    ct, ss_a = kem.encap_secret(pk)
                    ss_b = kem.decap_secret(ct)
                row.update({"ok": ss_a == ss_b, "pk_len": len(pk),
                            "ct_len": len(ct), "ss_len": len(ss_a)})
            except Exception as e:
                row.update({"ok": False, "error": str(e)})
        else:
            row["ok"] = False
        matrix.append(row)

    for a in sig_algos:
        row = {"algo": a, "family": "SIG", "enabled": a in enabled_sigs}
        if a in enabled_sigs:
            try:
                msg = b"pqc-qkd-hybrid crypto-agility probe"
                with oqs.Signature(a) as sig:
                    pk = sig.generate_keypair()
                    signature = sig.sign(msg)
                    ok = sig.verify(msg, signature, pk)
                row.update({"ok": bool(ok), "pk_len": len(pk),
                            "sig_len": len(signature)})
            except Exception as e:
                row.update({"ok": False, "error": str(e)})
        else:
            row["ok"] = False
        matrix.append(row)

    passed = sum(1 for r in matrix if r.get("ok"))
    return {
        "matrix": matrix,
        "summary": {"total": len(matrix), "passed": passed,
                    "all_pass": passed == len(matrix)},
        "library": "liboqs",
    }


class InteropRequest(BaseModel):
    algo: str = "ML-KEM-768"
    """Client's ML-KEM encapsulation key, base64. Produced by a DIFFERENT
    implementation -- @noble/post-quantum in the browser."""
    public_key_b64: str


@app.post("/api/interop/mlkem")
async def interop_mlkem(req: InteropRequest) -> dict[str, Any]:
    """Encapsulate to a client-supplied ML-KEM key and commit to the secret.

    This is what an independent cross-check has to do to be worth anything.
    The page previously compared liboqs and @noble on `ss_len` and `ct_len`:
    two implementations agreeing that ML-KEM-768 ciphertext is 1088 bytes shows
    only that both read the same table in FIPS 203. A completely wrong
    implementation produces 1088-byte ciphertexts too.

    Here the two implementations must interoperate. The browser generates a
    keypair with @noble, sends the encapsulation key, liboqs encapsulates to it
    in C, and the browser decapsulates the returned ciphertext. If the derived
    shared secrets match, two independently written implementations agree on
    the actual arithmetic -- which is the claim the panel makes.

    The shared secret is returned as a SHA-256 commitment rather than in the
    clear. The comparison is equally conclusive and no shared secret goes on
    the wire, which keeps this endpoint from being a key-disclosure oracle if
    it is ever pointed at something real.
    """
    if not _OQS_AVAILABLE:
        raise HTTPException(503, "liboqs not available")
    if req.algo not in oqs.get_enabled_kem_mechanisms():
        raise HTTPException(400, f"{req.algo} not enabled in this liboqs build")
    try:
        public_key = base64.b64decode(req.public_key_b64, validate=True)
    except Exception as e:
        raise HTTPException(400, f"public_key_b64 must be valid base64: {e}")

    with oqs.KeyEncapsulation(req.algo) as kem:
        expected = kem.details["length_public_key"]
        if len(public_key) != expected:
            # Rejected rather than passed to liboqs: a wrong-length key is a
            # client bug, and saying so beats a C-level failure.
            raise HTTPException(
                400,
                f"{req.algo} encapsulation key must be {expected} bytes, got {len(public_key)}",
            )
        ciphertext, shared_secret = kem.encap_secret(public_key)

    return {
        "algo": req.algo,
        "ciphertext_b64": base64.b64encode(ciphertext).decode(),
        "shared_secret_sha256": hashlib.sha256(shared_secret).hexdigest(),
        "ciphertext_len": len(ciphertext),
        "shared_secret_len": len(shared_secret),
        "server_impl": "liboqs",
        "note": (
            "Decapsulate ciphertext_b64 with your own secret key and compare "
            "SHA-256 of your shared secret to shared_secret_sha256."
        ),
    }


class KATRequest(BaseModel):
    algo: str = "ML-KEM-768"
    seed_hex: str


@app.post("/api/kat")
async def kat(req: KATRequest) -> dict[str, Any]:
    """Report liboqs sizes for an algorithm.

    Named `kat` and documented as a PQClean cross-check, but it was never
    either. `seed_hex` is parsed and only its LENGTH is reported -- nothing is
    seeded, so the result is not reproducible and not a known-answer test. The
    "PQClean check" is `os.path.isfile` on binaries this image never builds, so
    `pqclean_test_present` has always been false.

    Building them is not the fix: PQClean was archived on 2026-08-04, and its
    own retirement notice redirects to mlkem-native, mldsa-native and slhdsa-c.
    Depending on an archived project for a correctness claim would be a step
    backwards. The genuine cross-check is `/api/interop/mlkem`, which makes
    liboqs and the browser's independent implementation agree on a shared
    secret rather than on a length.

    Kept, with honest field names, because the size report is still useful.
    """
    if not _OQS_AVAILABLE:
        raise HTTPException(503, "liboqs not available")
    try:
        seed = bytes.fromhex(req.seed_hex)
    except ValueError:
        raise HTTPException(400, "seed_hex must be hex")
    with oqs.KeyEncapsulation(req.algo) as kem:
        pk = kem.generate_keypair()
        ct, ss = kem.encap_secret(pk)
    return {
        "algo": req.algo,
        "pk_len": len(pk),
        "ct_len": len(ct),
        "ss_len": len(ss),
        "seed_bytes_ignored": len(seed),
        "liboqs_ok": True,
        "is_known_answer_test": False,
        "cross_checked": False,
        "note": (
            "Sizes only. The seed is NOT used -- liboqs generates its own "
            "randomness, so this is not reproducible and not a KAT. For a real "
            "cross-check against an independent implementation use "
            "/api/interop/mlkem."
        ),
    }
