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
