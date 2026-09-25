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
    GET  /api/algorithms          every KEM / signature this liboqs build enables,
                                  with counts and the liboqs version
    POST /api/roundtrip           {algo} -> one keygen/encap/decap in liboqs,
                                  checked for self-consistency only
    POST /api/agility             {kems?, sigs?} -> the crypto-agility matrix: KEM
                                  encap/decap, and signature sign / verify / reject
                                  a tampered message, over DEFAULT_*_ALGOS or a
                                  subset of them
    POST /api/interop/mlkem       {algo, public_key_b64} -> liboqs encapsulates to
                                  a key another implementation generated
    POST /api/kat                 {algo, seed_hex} -> liboqs sizes only; NOT a
                                  known-answer test (see its docstring)

Earlier versions of this list described /api/kat as a "roundtrip + comparison"
and /api/roundtrip as running "both libs". Neither compared anything with a
second library, and the two endpoints that do the real work were missing.
"""
from __future__ import annotations

import base64
import hashlib
import logging
import os
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator

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
    """Every mechanism this liboqs build enables, in full.

    The lists used to be cut to their first 32 entries with nothing saying so.
    The pinned build enables 41 KEMs and 221 signature schemes, and the cut fell
    before the first SLH-DSA entry -- so this endpoint listed no SLH-DSA at all
    while the agility matrix ran three SLH-DSA parameter sets.
    """
    if not _OQS_AVAILABLE:
        raise HTTPException(503, "liboqs not available")
    kems = list(oqs.get_enabled_kem_mechanisms())
    sigs = list(oqs.get_enabled_sig_mechanisms())
    return {
        "liboqs": {"kems": kems, "sigs": sigs,
                   "n_kems": len(kems), "n_sigs": len(sigs),
                   "version": oqs.oqs_version()},
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


# Default crypto-agility matrix. Swapping algorithms = one list edit.
#
# KEMs span TWO families, for the reason the signature list below gives. The
# matrix was ML-KEM only, so a structural break in module lattices took out the
# whole KEM half. HQC (code-based) is the KEM NIST selected in March 2025 as the
# backup to ML-KEM; the pinned liboqs enables it by default. Its three sets
# cover categories 1, 3 and 5 like the ML-KEM rows, and cost 6 / 16 / 39 ms per
# round trip in the image (measured 2026-09-25). Classic McEliece is enabled
# too, but a 524,160-byte public key per row is not worth carrying here.
DEFAULT_KEM_ALGOS = ["ML-KEM-512", "ML-KEM-768", "ML-KEM-1024",
                     "HQC-1", "HQC-3", "HQC-5"]

# Signatures span TWO mathematical families on purpose.
#
# The matrix was ML-DSA only. Every entry in it -- and, then, every KEM above --
# rested on module lattices, so a structural break in that assumption took out
# the whole table at once. A matrix like that demonstrates parameter agility,
# not algorithm agility, and RFC 7696 is about having somewhere to move TO.
#
# SLH-DSA (FIPS 205) is hash-based and is that somewhere. The pinned liboqs
# exposes 156 SLH-DSA mechanisms; the three "s" sets at 128/192/256 cover NIST
# categories 1, 3 and 5.
#
# Note the naming: liboqs uses SLH_DSA_PURE_SHA2_128S while the browser side
# (@noble, src/lib/sim/pqc.ts) uses SLH-DSA-SHA2-128s. Same algorithm, two
# spellings. A name outside these lists is now refused (see AgilityRequest)
# rather than coming back as a quiet `enabled: false` row.
#
# SLH_DSA_PURE_SHA2_128F is here because the browser runs SLH-DSA-SHA2-128f and
# the server had no counterpart for it, so that row could never be compared.
DEFAULT_SIG_ALGOS = [
    "ML-DSA-44", "ML-DSA-65", "ML-DSA-87",
    "SLH_DSA_PURE_SHA2_128S", "SLH_DSA_PURE_SHA2_128F",
    "SLH_DSA_PURE_SHA2_192S", "SLH_DSA_PURE_SHA2_256S",
]

# The probe message, and the tampering applied to it for the negative check:
# the first byte XOR 0xFF, the same flip the browser applies in pqc.ts, so both
# implementations are put to the same test.
AGILITY_PROBE_MESSAGE = b"pqc-qkd-hybrid crypto-agility probe"
_TAMPER_MASK = 0xFF


def _tampered(msg: bytes) -> bytes:
    return bytes([msg[0] ^ _TAMPER_MASK]) + msg[1:]


class AgilityRequest(BaseModel):
    """A subset of the default matrix, or nothing (the whole default).

    Bounded, because this used to accept any list of any length and run every
    entry: about 0.6 s of CPU per SLH-DSA name, in a threadpool worker that
    keeps running after its caller has given up. Now:

      * the ALLOW-LIST is DEFAULT_KEM_ALGOS / DEFAULT_SIG_ALGOS -- a caller can
        choose among the rows, not add new ones;
      * a list longer than its allow-list is refused before anything runs
        (`max_length`), so a body of repeats cannot buy work;
      * repeats within the cap are dropped, first occurrence kept;
      * unknown fields are refused rather than ignored.
    """
    model_config = ConfigDict(extra="forbid")

    kems: list[str] | None = Field(default=None, max_length=len(DEFAULT_KEM_ALGOS))
    sigs: list[str] | None = Field(default=None, max_length=len(DEFAULT_SIG_ALGOS))

    @field_validator("kems", "sigs")
    @classmethod
    def _allowed_and_unique(cls, names: list[str] | None,
                            info: ValidationInfo) -> list[str] | None:
        if names is None:
            return None
        allowed = DEFAULT_KEM_ALGOS if info.field_name == "kems" else DEFAULT_SIG_ALGOS
        outside = [n for n in names if n not in allowed]
        if outside:
            raise ValueError(f"{outside} not in the matrix; accepted: {allowed}")
        return list(dict.fromkeys(names))


# Plain `def`, not `async def`. The matrix is a run of synchronous liboqs calls
# with no await between them -- SLH-DSA-256s signing alone is slow -- and under
# `async def` they ran ON the only event loop, so every other request queued
# behind them. That is where the demo's 503s on GET /api/pqc/algorithms came
# from (2026-09-25: the backend's 3 s timeout fired, and the validator logged
# the same GETs as 200 only after each agility POST finished). A plain `def`
# runs in FastAPI's threadpool.
@app.post("/api/agility")
def agility(req: AgilityRequest | None = None) -> dict[str, Any]:
    """Crypto-agility evidence: exercise a matrix of liboqs algorithms and
    report pass/fail per algorithm.

    Covers ML-KEM and HQC encap/decap, and ML-DSA and SLH-DSA sign/verify --
    two families on each side, so the table survives a structural break in
    either. Reporting only module-lattice schemes would have shown parameter
    agility while calling it algorithm agility.

    A signature row passes only if the genuine message verifies AND a tampered
    one is rejected (`verified`, `rejects_tampered`). It used to report
    `ok = verify(genuine)` alone, so a verify that accepted everything would
    have passed -- while /verify said both implementations had rejected a
    tampered message.

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
        # `verified` and `rejects_tampered` are None when the check did not
        # run (not enabled, or liboqs raised first): "not tested" is not the
        # same answer as "failed", and must not be written as False.
        row = {"algo": a, "family": "SIG", "enabled": a in enabled_sigs,
               "verified": None, "rejects_tampered": None}
        if a in enabled_sigs:
            try:
                msg = AGILITY_PROBE_MESSAGE
                with oqs.Signature(a) as sig:
                    pk = sig.generate_keypair()
                    signature = sig.sign(msg)
                    verified = bool(sig.verify(msg, signature, pk))
                    rejects_tampered = not sig.verify(_tampered(msg), signature, pk)
                row.update({"ok": verified and rejects_tampered,
                            "verified": verified,
                            "rejects_tampered": rejects_tampered,
                            "pk_len": len(pk), "sig_len": len(signature)})
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
        try:
            ciphertext, shared_secret = kem.encap_secret(public_key)
        except RuntimeError as e:
            # A key of the right LENGTH can still be refused: FIPS 203 §7.2
            # requires the encapsulation key to pass a modulus check, and liboqs
            # enforces it ("Can not encapsulate secret"). That is liboqs being
            # correct about a bad client key, which is a 400 -- it used to
            # escape as an unhandled 500.
            raise HTTPException(
                400, f"liboqs refused this {req.algo} encapsulation key "
                     f"(FIPS 203 input check): {e}")

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
    # Checked like /api/roundtrip: an unknown name was passed straight to
    # oqs.KeyEncapsulation, and its exception surfaced as a 500.
    if req.algo not in oqs.get_enabled_kem_mechanisms():
        raise HTTPException(400, f"unsupported algorithm: {req.algo}")
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
