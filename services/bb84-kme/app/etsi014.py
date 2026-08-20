"""ETSI GS QKD 014 V1.1.1 REST key-delivery API.

Two contracts are honoured here, and they differ:

1. The published specification (ETSI GS QKD 014 V1.1.1, 2019-02, clause 5.1)
   defines three methods, with **POST as the baseline** and GET as an optional
   convenience:

       GET  /api/v1/keys/{slave_SAE_ID}/status
       POST /api/v1/keys/{slave_SAE_ID}/enc_keys    body: {"number":N,"size":B}
       GET  /api/v1/keys/{slave_SAE_ID}/enc_keys?number=N&size=B
       POST /api/v1/keys/{master_SAE_ID}/dec_keys   body: {"key_IDs":[{"key_ID":"..."}]}
       GET  /api/v1/keys/{master_SAE_ID}/dec_keys?key_ID=...

   Note which SAE the path names: **enc_keys names the slave (the peer that
   will receive the key), dec_keys names the master (the peer that requested
   it)**. From either node's point of view that is always the *other* SAE,
   which is why one base URL serves both directions.

   `size` is in **bits** (GS QKD 004 uses bytes -- a common porting bug).

2. The arnika client (submodules/arnika/repositories/kms.go:94-101) issues only
   the GET forms, so those are kept for interoperability with the binary this
   testbed actually runs.

Edition 2 of GS QKD 014 (work item RGS/QKD-014ed2_KeyDeliv, stable draft) is a
breaking change -- paths move to /kdapi/v2/, GET is removed, SAE IDs move from
the URL into the request body and master/slave become initiator/target. It is
not implemented here; see docs/references.md.
"""
from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/keys", tags=["etsi-014"])


class KeyDTO(BaseModel):
    key_ID: str = Field(..., description="UUID identifying this key")
    key: str = Field(..., description="Base64-encoded key material")


class KeysResponse(BaseModel):
    keys: list[KeyDTO]


class KeyRequest(BaseModel):
    """Body of POST .../enc_keys (spec clause 6.1)."""

    number: int = Field(1, ge=1, description="Number of keys requested")
    size: int = Field(256, description="Key size in BITS (not bytes)")


class KeyID(BaseModel):
    key_ID: str = Field(..., description="UUID of a previously delivered key")


class KeyIDs(BaseModel):
    """Body of POST .../dec_keys (spec clause 6.3).

    `key_IDs` is an array of *objects*, each holding a `key_ID` -- not an array
    of bare strings. Getting this wrong is one of the most common 014 interop
    failures.
    """

    key_IDs: list[KeyID] = Field(..., min_length=1)


class KMEStatus(BaseModel):
    source_KME_ID: str
    target_KME_ID: str
    master_SAE_ID: str
    slave_SAE_ID: str
    key_size: int
    stored_key_count: int
    max_key_count: int
    max_key_per_request: int = 1
    max_key_size: int = 1024
    min_key_size: int = 64
    max_SAE_ID_count: int = 0


@router.get("/{sae_id}/status", response_model=KMEStatus)
async def status(sae_id: str, request: Request) -> KMEStatus:
    pool = request.app.state.pool
    stats = pool.stats()
    return KMEStatus(
        source_KME_ID=pool.sae_id,
        target_KME_ID=sae_id,
        master_SAE_ID=pool.sae_id,
        slave_SAE_ID=sae_id,
        key_size=pool.key_size_bits,
        stored_key_count=stats.pool_size,
        max_key_count=pool.capacity,
    )


async def _take_enc_keys(pool, sae_id: str, number: int, size: int) -> KeysResponse:
    """Shared implementation of the GET and POST enc_keys forms."""
    if size != pool.key_size_bits:
        raise HTTPException(
            status_code=400,
            detail=(
                f"unsupported key size {size} bits; this KME emits "
                f"{pool.key_size_bits}-bit keys (size is in bits, per GS QKD 014)"
            ),
        )

    keys: list[KeyDTO] = []
    for _ in range(number):
        sk = await pool.pop_for_enc(slave_sae_id=sae_id)
        if sk is None:
            raise HTTPException(status_code=503, detail="key pool empty")
        keys.append(KeyDTO(key_ID=sk.key_id, key=sk.key_b64))
    return KeysResponse(keys=keys)


@router.get("/{sae_id}/enc_keys", response_model=KeysResponse)
async def enc_keys_get(
    sae_id: str,
    request: Request,
    number: Annotated[int, Query(ge=1, le=1)] = 1,
    size: Annotated[int, Query(ge=8, le=4096)] = 256,
) -> KeysResponse:
    """Get key (GET form). `sae_id` is the SLAVE SAE that will receive the key."""
    return await _take_enc_keys(request.app.state.pool, sae_id, number, size)


@router.post("/{sae_id}/enc_keys", response_model=KeysResponse)
async def enc_keys_post(sae_id: str, body: KeyRequest, request: Request) -> KeysResponse:
    """Get key (POST form -- the specification's baseline)."""
    return await _take_enc_keys(request.app.state.pool, sae_id, body.number, body.size)


async def _resolve_dec_keys(pool, sae_id: str, key_ids: list[str]) -> KeysResponse:
    keys: list[KeyDTO] = []
    for key_id in key_ids:
        sk = await pool.get_by_id(key_id, master_sae_id=sae_id)
        if sk is None:
            raise HTTPException(status_code=404, detail=f"unknown key_ID: {key_id}")
        keys.append(KeyDTO(key_ID=sk.key_id, key=sk.key_b64))
    return KeysResponse(keys=keys)


@router.get("/{sae_id}/dec_keys", response_model=KeysResponse)
async def dec_keys_get(
    sae_id: str,
    request: Request,
    key_ID: Annotated[str, Query(min_length=1)],
) -> KeysResponse:
    """Get key with key IDs (GET form). `sae_id` is the MASTER SAE."""
    return await _resolve_dec_keys(request.app.state.pool, sae_id, [key_ID])


@router.post("/{sae_id}/dec_keys", response_model=KeysResponse)
async def dec_keys_post(sae_id: str, body: KeyIDs, request: Request) -> KeysResponse:
    """Get key with key IDs (POST form -- supports batches)."""
    return await _resolve_dec_keys(
        request.app.state.pool, sae_id, [k.key_ID for k in body.key_IDs]
    )
