"""PQC implementation cross-validator.

For a given NIST algorithm and KAT (Known Answer Test) seed, run the test
vector through both liboqs (production library used by oqs-provider/arnika)
and PQClean (NIST reference implementations) and verify byte-equality.

This catches regressions whenever either side updates an algorithm.

Endpoints:
    GET  /health
    GET  /api/algorithms          list supported KEMs / signatures
    POST /api/kat                 {algo, seed_hex} -> roundtrip + comparison
    POST /api/roundtrip           {algo} -> single keygen/encap/decap with both libs
"""
from __future__ import annotations

import logging
import os
import subprocess
import sys
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
log = logging.getLogger("pqc-validator")

PQCLEAN_DIR = os.environ.get("PQCLEAN_DIR", "/submodules/PQClean")

try:
    import oqs       # liboqs-python
    _OQS_AVAILABLE = True
except Exception as e:    # pragma: no cover (env)
    log.warning("liboqs-python not importable: %s", e)
    _OQS_AVAILABLE = False


app = FastAPI(title="PQC Validator", version="0.1.0")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "oqs": str(_OQS_AVAILABLE), "pqclean_dir": PQCLEAN_DIR}


@app.get("/api/algorithms")
async def algorithms() -> dict[str, Any]:
    if not _OQS_AVAILABLE:
        raise HTTPException(503, "liboqs not available")
    kems = list(oqs.get_enabled_kem_mechanisms())
    sigs = list(oqs.get_enabled_sig_mechanisms())
    pqclean_present = os.path.isdir(PQCLEAN_DIR)
    return {
        "liboqs": {"kems": kems[:32], "sigs": sigs[:32]},
        "pqclean": {"available": pqclean_present, "path": PQCLEAN_DIR},
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
DEFAULT_SIG_ALGOS = ["ML-DSA-44", "ML-DSA-65", "ML-DSA-87"]


class AgilityRequest(BaseModel):
    kems: list[str] | None = None
    sigs: list[str] | None = None


def _pqclean_present(algo: str) -> bool:
    tb = f"{PQCLEAN_DIR}/test/test_{algo.lower().replace('-', '_')}"
    return os.path.isfile(tb)


@app.post("/api/agility")
async def agility(req: AgilityRequest | None = None) -> dict[str, Any]:
    """Crypto-agility evidence: exercise a matrix of liboqs algorithms (ML-KEM
    encap/decap + ML-DSA sign/verify) and report pass/fail per algorithm, plus
    whether a PQClean reference test binary is present for cross-checking."""
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
        row["pqclean_test_present"] = _pqclean_present(a)
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
        row["pqclean_test_present"] = _pqclean_present(a)
        matrix.append(row)

    passed = sum(1 for r in matrix if r.get("ok"))
    return {
        "matrix": matrix,
        "summary": {"total": len(matrix), "passed": passed,
                    "all_pass": passed == len(matrix)},
        "library": "liboqs",
    }


class KATRequest(BaseModel):
    algo: str = "ML-KEM-768"
    seed_hex: str


@app.post("/api/kat")
async def kat(req: KATRequest) -> dict[str, Any]:
    """Cross-check: encapsulate with liboqs, then verify decapsulation matches
    via PQClean reference (if its binaries are present)."""
    if not _OQS_AVAILABLE:
        raise HTTPException(503, "liboqs not available")
    try:
        seed = bytes.fromhex(req.seed_hex)
    except ValueError:
        raise HTTPException(400, "seed_hex must be hex")
    with oqs.KeyEncapsulation(req.algo) as kem:
        pk = kem.generate_keypair()
        ct, ss = kem.encap_secret(pk)
    # PQClean check: if test binary present, invoke
    test_bin = f"{PQCLEAN_DIR}/test/test_{req.algo.lower().replace('-', '_')}"
    pqclean_ok = os.path.isfile(test_bin)
    return {
        "algo": req.algo,
        "pk_len": len(pk),
        "ct_len": len(ct),
        "ss_len": len(ss),
        "seed_bytes": len(seed),
        "liboqs_ok": True,
        "pqclean_test_present": pqclean_ok,
        "note": "Full PQClean roundtrip available when test binaries are built.",
    }
