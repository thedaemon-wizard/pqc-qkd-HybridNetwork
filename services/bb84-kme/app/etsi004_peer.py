"""HTTP link from one KME's ETSI GS QKD 004 engine to its peer's.

Calls the peer's `/internal/etsi004/*` routes -- the same trust model as
`/internal/sync`: unauthenticated, reachable only on qkd-net and mgmt-net, and
never proxied by webui-backend or nginx (tests/test_the_004_binding_is_not_public.py).

Every failure maps to one engine exception, so the engine can choose the
status: an unreachable peer is status 4, a peer that does not answer within the
call's Timeout is status 6, and a peer that no longer knows the stream (HTTP
404) closes it.
"""
from __future__ import annotations

import httpx

from .etsi004_engine import ChunkConflict, PeerLostStream, PeerTimeout, PeerUnreachable


class HttpPeerLink:
    def __init__(self, base_url: str, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.base = base_url.rstrip("/") + "/internal/etsi004"
        # None in the service. tests/test_etsi004_http_binding.py passes an
        # ASGI transport so two KME apps talk over the real routes in-process.
        self.transport = transport

    async def _post(self, path: str, body: dict, timeout_s: float) -> dict:
        try:
            async with httpx.AsyncClient(timeout=timeout_s, transport=self.transport) as client:
                r = await client.post(f"{self.base}/{path}", json=body)
        except httpx.TimeoutException as e:
            raise PeerTimeout(str(e)) from e
        except httpx.HTTPError as e:
            raise PeerUnreachable(str(e)) from e
        if r.status_code == 404:
            raise PeerLostStream(body.get("Key_stream_ID", ""))
        if r.status_code == 409:
            raise ChunkConflict(body.get("Key_stream_ID", ""))
        if r.status_code >= 400:
            raise PeerUnreachable(f"peer answered HTTP {r.status_code}")
        return r.json() if r.content else {}

    async def announce(self, ksid: str, apps: dict, qos: dict, timeout_s: float) -> None:
        await self._post("announce", {"Key_stream_ID": ksid, "apps": apps, "QoS": qos}, timeout_s)

    async def establish(self, ksid: str, timeout_s: float) -> None:
        await self._post("establish", {"Key_stream_ID": ksid}, timeout_s)

    async def allocate(self, ksid: str, index: int, timeout_s: float) -> dict:
        return await self._post("allocate", {"Key_stream_ID": ksid, "index": index}, timeout_s)

    async def chunk(self, ksid: str, index: int, key_ids: list[str], data_b64: str,
                    timeout_s: float) -> None:
        await self._post("chunk", {"Key_stream_ID": ksid, "index": index,
                                   "key_IDs": key_ids, "Key_buffer": data_b64}, timeout_s)

    async def close(self, ksid: str, timeout_s: float) -> None:
        await self._post("close", {"Key_stream_ID": ksid}, timeout_s)

    async def withdraw(self, ksid: str, timeout_s: float) -> None:
        await self._post("withdraw", {"Key_stream_ID": ksid}, timeout_s)
