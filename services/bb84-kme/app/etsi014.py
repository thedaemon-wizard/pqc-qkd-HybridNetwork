"""ETSI GS QKD 014 REST endpoints — byte-for-byte compatible with arnika-vq.

Reference contract (arnika-vq):
    submodules/arnika-vq/kms/kms.go:69-76   --> JSON schema
        type Key struct {
            ID  string `json:"key_ID"`
            Key string `json:"key"`
        }
    submodules/arnika-vq/kms/kms.go:126-134 --> URL forms
        GET .../{SAE}/enc_keys?number=N&size=B
        GET .../{SAE}/dec_keys?key_ID=...
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
        key_size=256,
        stored_key_count=stats.pool_size,
        max_key_count=pool.capacity,
    )


@router.get("/{sae_id}/enc_keys", response_model=KeysResponse)
async def enc_keys(
    sae_id: str,
    request: Request,
    number: Annotated[int, Query(ge=1, le=1)] = 1,
    size: Annotated[int, Query(ge=8, le=4096)] = 256,
) -> KeysResponse:
    if size != 256:
        # The arnika integration always asks for 256
        raise HTTPException(status_code=400, detail="only size=256 supported in this PoC")
    pool = request.app.state.pool

    keys: list[KeyDTO] = []
    for _ in range(number):
        sk = await pool.pop_for_enc()
        if sk is None:
            raise HTTPException(status_code=503, detail="key pool empty")
        keys.append(KeyDTO(key_ID=sk.key_id, key=sk.key_b64))
    return KeysResponse(keys=keys)


@router.get("/{sae_id}/dec_keys", response_model=KeysResponse)
async def dec_keys(
    sae_id: str,
    request: Request,
    key_ID: Annotated[str, Query(min_length=1)],
) -> KeysResponse:
    pool = request.app.state.pool
    sk = await pool.get_by_id(key_ID)
    if sk is None:
        raise HTTPException(status_code=404, detail=f"unknown key_ID: {key_ID}")
    return KeysResponse(keys=[KeyDTO(key_ID=sk.key_id, key=sk.key_b64)])
