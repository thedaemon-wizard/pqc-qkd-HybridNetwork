"""ETSI GS QKD 004 V2.1.1 over this project's own HTTP/JSON binding.

V2.1.1 defines an abstract interface -- OPEN_CONNECT, GET_KEY, CLOSE -- and no
wire format. This binding is ours, documented in docs/etsi004-binding.md:

  POST /etsi004/v2.1.1/open_connect   {source, destination, QoS?, Key_stream_ID?}
  POST /etsi004/v2.1.1/get_key        {Key_stream_ID, index?, Metadata?: {Metadata_size}}
  POST /etsi004/v2.1.1/close          {Key_stream_ID}

Every protocol outcome is HTTP 200 with the 004 `status` in the body. HTTP 422
is a malformed request (a bad UUID, a value outside uint32, an unknown field);
HTTP 404 is a Key_stream_ID this KM does not know, or the binding switched off
(`etsi004.endpoint_enabled`, false on the public demo). Key_chunk_size is in
BYTES -- ETSI GS QKD 014 sizes keys in bits.

The peer-facing routes under /internal/etsi004 carry the KM-to-KM exchange and
are hidden from the schema.
"""
from __future__ import annotations

import math
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from . import config_loader as cl
from .etsi004_engine import ChunkConflict, Limits, UnknownStream
from .etsi004_spec import binding, load_spec, uint32_max

U32 = Annotated[int, Field(ge=0, le=uint32_max())]
URI = Annotated[str, Field(min_length=3, max_length=binding()["uri_max_length"],
                           pattern=r"^[A-Za-z][A-Za-z0-9+.-]*:")]


def limits() -> Limits:
    """The etsi004 section of config/qkd_params.yaml, read on every call.

    `max_pool_share` is checked against the pool here as well as at startup,
    because the file is hot-reloaded: 004 chunks, the 014 floor on this KME
    and the peer's replicas must all fit in one ring buffer, or the buffer
    evicts keys the other side still needs.
    """
    lim = Limits(
        max_streams=int(cl.require("etsi004.max_streams")),
        max_pool_share=float(cl.require("etsi004.max_pool_share")),
        default_timeout_ms=int(cl.require("etsi004.default_timeout_ms")),
        max_timeout_ms=int(cl.require("etsi004.max_timeout_ms")),
        default_ttl_s=int(cl.require("etsi004.default_ttl_s")),
        max_ttl_s=int(cl.require("etsi004.max_ttl_s")),
        uint32_max=uint32_max(),
        preferred_mimetype=binding()["preferred_metadata_mimetype"],
    )
    capacity = int(cl.require("simulator.pool_max_size"))
    watermark = int(cl.require("simulator.pool_low_watermark"))
    share = math.floor(lim.max_pool_share * capacity)
    if not 0 < lim.max_pool_share < 1 or 2 * watermark + share > capacity:
        raise ValueError(
            f"etsi004.max_pool_share={lim.max_pool_share} gives {share} keys; with "
            f"pool_low_watermark={watermark} it must satisfy 2*{watermark} + share <= "
            f"pool_max_size={capacity}")
    return lim


def _enabled() -> None:
    # Read on every request, so a config reload switches it without a restart.
    if not cl.require("etsi004.endpoint_enabled"):
        raise HTTPException(404, "etsi004.endpoint_enabled=false")


def _engine(request: Request):
    return request.app.state.etsi004


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class QoSModel(_Strict):
    Key_chunk_size: U32 | None = Field(None, description="bytes (not bits, as in GS QKD 014); null or 0 = one produced key")
    Max_bps: U32 | None = Field(None, description="bit/s")
    Min_bps: U32 | None = Field(None, description="bit/s")
    Jitter: U32 | None = Field(None, description="bit/s; echoed, not enforced")
    Priority: U32 | None = Field(None, description="echoed, not enforced (consideration 4)")
    Timeout: U32 | None = Field(None, description="ms; clamped to etsi004.max_timeout_ms")
    TTL: U32 | None = Field(None, description="s; clamped to etsi004.max_ttl_s")
    Metadata_mimetype: str | None = Field(None, max_length=load_spec()["mimetype_max_bytes"])


class OpenConnectRequest(_Strict):
    source: URI
    destination: URI
    QoS: QoSModel | None = None
    Key_stream_ID: UUID | None = None


class MetadataIn(_Strict):
    Metadata_size: U32


class GetKeyRequest(_Strict):
    Key_stream_ID: UUID
    index: U32 | None = None
    Metadata: MetadataIn | None = None


class CloseRequest(_Strict):
    Key_stream_ID: UUID


def _public(r: dict) -> dict:
    """The engine's result without internal fields; `transition` stays, as
    documentation of which rule answered."""
    return {k: v for k, v in r.items() if v is not None or k == "status"}


router = APIRouter(prefix=binding()["prefix"], tags=["etsi-004 V2.1.1 (project HTTP/JSON binding)"],
                   dependencies=[Depends(_enabled)])


@router.post("/open_connect")
async def open_connect(req: OpenConnectRequest, request: Request) -> dict:
    qos = req.QoS.model_dump() if req.QoS else None
    ksid = str(req.Key_stream_ID) if req.Key_stream_ID else None
    return _public(await _engine(request).open_connect(req.source, req.destination, qos, ksid))


@router.post("/get_key")
async def get_key(req: GetKeyRequest, request: Request) -> dict:
    size = req.Metadata.Metadata_size if req.Metadata else 0
    try:
        return _public(await _engine(request).get_key(str(req.Key_stream_ID), req.index, size))
    except UnknownStream:
        raise HTTPException(binding()["unknown_ksid_http"], "unknown or closed Key_stream_ID") from None


@router.post("/close")
async def close(req: CloseRequest, request: Request) -> dict:
    try:
        return _public(await _engine(request).close(str(req.Key_stream_ID)))
    except UnknownStream:
        raise HTTPException(binding()["unknown_ksid_http"], "unknown Key_stream_ID") from None


# ---- KM-to-KM -----------------------------------------------------------------
class _PeerBody(BaseModel):
    Key_stream_ID: str
    apps: dict | None = None
    QoS: dict | None = None
    index: int | None = None
    key_IDs: list[str] | None = None
    Key_buffer: str | None = None


peer_router = APIRouter(prefix="/internal/etsi004", include_in_schema=False,
                        dependencies=[Depends(_enabled)])


async def _peer_call(fn, *args):
    try:
        return await fn(*args) or {}
    except UnknownStream:
        raise HTTPException(404, "unknown Key_stream_ID") from None
    except ChunkConflict:
        raise HTTPException(409, "conflicting chunk or stream") from None


@peer_router.post("/announce")
async def p_announce(b: _PeerBody, request: Request) -> dict:
    return await _peer_call(_engine(request).on_announce, b.Key_stream_ID, b.apps or {}, b.QoS or {})


@peer_router.post("/establish")
async def p_establish(b: _PeerBody, request: Request) -> dict:
    return await _peer_call(_engine(request).on_establish, b.Key_stream_ID)


@peer_router.post("/allocate")
async def p_allocate(b: _PeerBody, request: Request) -> dict:
    return await _peer_call(_engine(request).on_allocate, b.Key_stream_ID, int(b.index or 0))


@peer_router.post("/chunk")
async def p_chunk(b: _PeerBody, request: Request) -> dict:
    return await _peer_call(_engine(request).on_chunk, b.Key_stream_ID, int(b.index or 0),
                            b.key_IDs or [], b.Key_buffer or "")


@peer_router.post("/close")
async def p_close(b: _PeerBody, request: Request) -> dict:
    return await _peer_call(_engine(request).on_close, b.Key_stream_ID)


@peer_router.post("/withdraw")
async def p_withdraw(b: _PeerBody, request: Request) -> dict:
    return await _peer_call(_engine(request).on_withdraw, b.Key_stream_ID)
