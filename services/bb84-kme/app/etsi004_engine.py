"""ETSI GS QKD 004 V2.1.1 key-stream engine for one KME (no web framework).

Each KME runs one engine. The two engines keep a record per Key_stream_ID and
talk through a `PeerLink` (HTTP in the service, in-memory in the tests). The
transition ids (T1-T22) are the ones in `etsi004SpecV211.json`; each method
reports the one it took, and tests/test_etsi004_state_machine.py checks that
every transition in the file is exercised.

How both KMEs end up with identical bytes:
  1. Exactly one KME creates chunks: the ALLOCATOR, the one whose SAE_ID sorts
     first. The other asks it to allocate and receives the chunk by push.
     (Clause 6.1, consideration 3, leaves the KM's internals to the implementer;
     this split is this project's choice.)
  2. A chunk is immutable once created. A repeated push of the same bytes is
     acknowledged; different bytes for the same index are refused (409).
  3. The allocator hands chunk i to its own application only after the peer
     confirmed storing it, so neither side can deliver a key the other lacks.
  4. No lock is held across a call to the peer. The peer's handler may call
     back (allocate -> chunk), and a lock held across that would deadlock.

How 004 and 014 share one key pool (this project's policy, set by the user):
  * a 004 chunk never leaves fewer than `low_watermark` dispensable keys for
    ETSI GS QKD 014 (the "014 floor", enforced in KeyPool);
  * undelivered 004 chunks may hold at most `max_pool_share` of the pool
    (16 of 64 keys by default);
  * keys moved into a stream are removed from BOTH sides' 014 index, so no
    004 key can ever be resolved through 014 `dec_keys`.

Policy decisions recorded in the spec file: GET_KEY with no key available
returns status 2 at once and requests production (T13); status 6 is kept for a
peer KM that does not acknowledge within Timeout (T14); an unknown or closed
Key_stream_ID is HTTP 404 (T20); indices start at 0 and a null index means
"the next one not yet delivered to this side".

In-memory state: this needs a single worker process, and CPython cannot
guarantee that key bytes are zeroized -- `bytearray`s are cleared on erase,
but copies made along the way are not under our control.
"""
from __future__ import annotations

import asyncio
import base64
import json
import math
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from .etsi004_spec import Etsi004Status as S
from .etsi004_spec import StreamState as St


class UnknownStream(Exception):
    """No record of this Key_stream_ID here: HTTP 404 in the binding (T20)."""


class ChunkConflict(Exception):
    """A push carried different bytes for an index already stored (HTTP 409)."""


class PeerUnreachable(Exception):
    """The peer KM could not be reached (maps to status 4)."""


class PeerTimeout(Exception):
    """The peer KM did not answer within the call's Timeout (maps to status 6)."""


class PeerLostStream(Exception):
    """The peer KM answered 404 for this stream (maps to status 4, closes it)."""


class PeerLink(Protocol):
    async def announce(self, ksid: str, apps: dict, qos: dict, timeout_s: float) -> None: ...
    async def establish(self, ksid: str, timeout_s: float) -> None: ...
    async def allocate(self, ksid: str, index: int, timeout_s: float) -> dict: ...
    async def chunk(self, ksid: str, index: int, key_ids: list[str], data_b64: str,
                    timeout_s: float) -> None: ...
    async def close(self, ksid: str, timeout_s: float) -> None: ...
    async def withdraw(self, ksid: str, timeout_s: float) -> None: ...


class KeySource(Protocol):
    key_bytes: int
    capacity: int
    low_watermark: int
    async def take_local_for_stream(self, n: int) -> list[Any] | None: ...
    def request_extra(self, n: int) -> None: ...
    def release_extra(self) -> None: ...
    async def drop_replicas(self, key_ids: list[str]) -> None: ...
    def production_capacity_bps(self) -> float | None: ...


@dataclass(frozen=True)
class Limits:
    max_streams: int
    max_pool_share: float
    default_timeout_ms: int
    max_timeout_ms: int
    default_ttl_s: int
    max_ttl_s: int
    uint32_max: int
    preferred_mimetype: str


@dataclass
class Chunk:
    index: int
    key_ids: list[str]
    data: bytearray
    created_at: float
    confirmed_at_peer: bool = False
    delivered: bool = False

    def erase(self) -> None:
        for i in range(len(self.data)):
            self.data[i] = 0


@dataclass
class Stream:
    ksid: str
    apps: dict
    qos: dict
    allocator: bool
    local_open: bool = False
    peer_open: bool = False
    local_closed: bool = False
    peer_closed: bool = False
    state: St = St.PENDING_PEER
    chunks: dict[int, Chunk] = field(default_factory=dict)
    delivered: set[int] = field(default_factory=set)
    next_alloc: int = 0
    last_activity: float = 0.0
    closed_at: float | None = None
    established: asyncio.Event = field(default_factory=asyncio.Event)

    def wipe(self) -> None:
        for c in self.chunks.values():
            c.erase()
        self.chunks.clear()

    def held_keys(self) -> int:
        """Keys sitting in chunks this side has not delivered."""
        return sum(len(c.key_ids) for c in self.chunks.values() if not c.delivered)


def _same_apps(a: dict, b: dict) -> bool:
    return (a["source"] == b["source"] and a["destination"] == b["destination"]) or \
           (a["source"] == b["destination"] and a["destination"] == b["source"])


def _res(status: S | None, transition: str, **kw) -> dict:
    return {"status": None if status is None else int(status), "transition": transition, **kw}


class Etsi004Engine:
    def __init__(self, *, sae_id: str, peer_sae_id: str, keys: KeySource, peer: PeerLink,
                 clock: Callable[[], float], limits: Callable[[], Limits],
                 new_ksid: Callable[[], str] = lambda: str(uuid.uuid4())) -> None:
        self.sae_id = sae_id
        self.peer_sae_id = peer_sae_id
        # The allocator is the KME whose SAE_ID sorts first (ALICE here).
        self.is_allocator = sae_id < peer_sae_id
        self.keys = keys
        self.peer = peer
        self.clock = clock
        self.limits = limits
        self.new_ksid = new_ksid
        self.streams: dict[str, Stream] = {}

    # ------------------------------------------------------------------ helpers
    def _timeout_s(self, qos: dict) -> float:
        lim = self.limits()
        t = qos.get("Timeout")
        ms = lim.default_timeout_ms if t in (None, 0) else min(int(t), lim.max_timeout_ms)
        return ms / 1000.0

    def _ttl_s(self, qos: dict) -> int:
        lim = self.limits()
        t = qos.get("TTL")
        return lim.default_ttl_s if t in (None, 0) else min(int(t), lim.max_ttl_s)

    def _cap_keys(self) -> int:
        return math.floor(self.limits().max_pool_share * self.keys.capacity)

    def _open_count(self) -> int:
        return sum(1 for s in self.streams.values() if s.state in (St.PENDING_PEER, St.ESTABLISHED))

    def _reserved_bps(self, exclude: str | None = None) -> float:
        return float(sum(int(s.qos.get("Min_bps") or 0) for k, s in self.streams.items()
                         if k != exclude and s.state in (St.PENDING_PEER, St.ESTABLISHED)))

    def _negotiate(self, qos_in: dict | None) -> tuple[dict, str | None]:
        """The registered QoS, and why it cannot be met (None when it can)."""
        lim = self.limits()
        q = dict(qos_in or {})
        k = self.keys.key_bytes
        cap_bytes = self._cap_keys() * k
        out = {
            "Key_chunk_size": q.get("Key_chunk_size") or k,
            "Max_bps": q.get("Max_bps"), "Min_bps": q.get("Min_bps"),
            "Jitter": q.get("Jitter"), "Priority": q.get("Priority"),
            "Timeout": min(int(q["Timeout"]), lim.max_timeout_ms) if q.get("Timeout") else lim.default_timeout_ms,
            "TTL": min(int(q["TTL"]), lim.max_ttl_s) if q.get("TTL") else lim.default_ttl_s,
            "Metadata_mimetype": q.get("Metadata_mimetype") or None,
        }
        why = None
        size = out["Key_chunk_size"]
        if size % k != 0:
            out["Key_chunk_size"] = max(k, math.floor(size / k + 0.5) * k)
            why = f"Key_chunk_size must be a multiple of {k} bytes (one produced key)"
        elif size > cap_bytes:
            out["Key_chunk_size"] = cap_bytes
            why = f"Key_chunk_size above what one stream may hold ({cap_bytes} bytes)"
        want = int(out["Min_bps"] or 0)
        if want > 0:
            measured = self.keys.production_capacity_bps()
            available = 0.0 if measured is None else max(0.0, measured - self._reserved_bps())
            if want > available:
                out["Min_bps"] = math.floor(available)
                why = why or ("Min_bps above measured production minus existing reservations"
                              if measured is not None else "no round accepted yet, so no rate can be promised")
        if out["Max_bps"] is not None:
            measured = self.keys.production_capacity_bps()
            if measured is not None:
                out["Max_bps"] = min(int(out["Max_bps"]), math.floor(measured))
        mt = out["Metadata_mimetype"]
        if mt and mt != lim.preferred_mimetype:
            out["Metadata_mimetype"] = lim.preferred_mimetype
            why = why or f"only {lim.preferred_mimetype} metadata is supported"
        return out, why

    def _touch(self, s: Stream) -> None:
        s.last_activity = self.clock()

    # --------------------------------------------------------- application API
    async def open_connect(self, source: str, destination: str, qos: dict | None,
                           ksid: str | None) -> dict:
        apps = {"source": source, "destination": destination}
        if ksid is not None:
            s = self.streams.get(ksid)
            if s is not None:
                if not _same_apps(s.apps, apps):
                    return _res(S.KSID_IN_USE, "T7", Key_stream_ID=ksid,
                                detail="Key_stream_ID belongs to another application pair")
                if s.state == St.CLOSED or s.peer_closed:
                    return _res(S.KSID_IN_USE, "T9", Key_stream_ID=ksid,
                                detail="a closed Key_stream_ID is not reused")
                if s.local_open:
                    return _res(S.KSID_IN_USE, "T8", Key_stream_ID=ksid,
                                detail="this KM already opened the stream")
                # The peer application opened first (T1 there, or a predefined
                # id there): confirm with the peer KM, then commit here.
                try:
                    await self.peer.establish(ksid, self._timeout_s(s.qos))
                except (PeerUnreachable, PeerLostStream):
                    return _res(S.NO_QKD_CONNECTION, "T3", Key_stream_ID=ksid,
                                detail="the peer KM could not confirm the stream")
                except PeerTimeout:
                    return _res(S.TIMEOUT, "T6", Key_stream_ID=ksid,
                                detail="the peer KM did not confirm within Timeout")
                s.local_open = True
                s.state = St.ESTABLISHED
                s.established.set()
                self._touch(s)
                return _res(S.SUCCESSFUL, "T5", Key_stream_ID=ksid, QoS=dict(s.qos))

        registered, why = self._negotiate(qos)
        if why:
            return _res(S.QOS_NOT_MET, "T2", Key_stream_ID=None, QoS=registered, detail=why)
        if self._open_count() >= self.limits().max_streams:
            return _res(S.NO_QKD_CONNECTION, "T4", Key_stream_ID=None,
                        detail=f"stream limit reached ({self.limits().max_streams})")
        new_id = ksid or self.new_ksid()
        s = Stream(ksid=new_id, apps=apps, qos=registered, allocator=self.is_allocator,
                   local_open=True, last_activity=self.clock())
        self.streams[new_id] = s
        timeout = self._timeout_s(registered)
        try:
            await self.peer.announce(new_id, apps, registered, timeout)
        except ChunkConflict:
            # The peer KM holds this id for another application pair, or as a
            # closed stream.
            del self.streams[new_id]
            return _res(S.KSID_IN_USE, "T7", Key_stream_ID=new_id,
                        detail="the peer KM holds this Key_stream_ID for another stream")
        except (PeerUnreachable, PeerLostStream, PeerTimeout):
            del self.streams[new_id]
            return _res(S.NO_QKD_CONNECTION, "T3", Key_stream_ID=None,
                        detail="the peer KM is unreachable")
        if ksid is None:
            return _res(S.PEER_NOT_CONNECTED, "T1", Key_stream_ID=new_id, QoS=dict(registered))
        # A predefined Key_stream_ID: block until the peer application opens it
        # or Timeout passes (clause 6.2.4), then roll back on both KMs.
        try:
            await asyncio.wait_for(s.established.wait(), timeout=timeout)
        except TimeoutError:
            self.streams.pop(new_id, None)
            try:
                await self.peer.withdraw(new_id, timeout)
            except (PeerUnreachable, PeerLostStream, PeerTimeout):
                pass
            return _res(S.TIMEOUT, "T6", Key_stream_ID=new_id,
                        detail="the peer application did not open within Timeout")
        return _res(S.SUCCESSFUL, "T6", Key_stream_ID=new_id, QoS=dict(s.qos))

    async def get_key(self, ksid: str, index: int | None, metadata_size: int) -> dict:
        s = self.streams.get(ksid)
        # A stream this application closed is as unknown to it as one that
        # never existed (the user's policy: unknown or closed -> HTTP 404).
        if s is None or s.state == St.CLOSED or s.local_closed:
            raise UnknownStream(ksid)
        self._touch(s)
        if s.state == St.PENDING_PEER:
            return _res(S.PEER_APP_NOT_CONNECTED, "T10", index=None)
        want = index if index is not None else self._next_undelivered(s)
        if want in s.delivered:
            return _res(S.INSUFFICIENT_KEY, "T21", index=want,
                        detail="that index was already delivered here and erased")
        chunk = s.chunks.get(want)
        if chunk is None or (s.allocator and not chunk.confirmed_at_peer):
            if s.peer_closed:
                return _res(S.INSUFFICIENT_KEY, "T19", index=want,
                            detail="the peer closed; only chunks already allocated are held")
            got = await self._obtain(s, want)
            if got is not None:
                return got
            chunk = s.chunks.get(want)
            if chunk is None:
                return _res(S.INSUFFICIENT_KEY, "T13", index=want, detail="no chunk yet")
        u32 = self.limits().uint32_max
        age_ms = min(u32, max(0, round((self.clock() - chunk.created_at) * 1000)))
        meta = json.dumps({"age": age_ms, "hops": 0}, separators=(",", ":"))
        need = len(meta.encode())
        if metadata_size and metadata_size < need:
            # Nothing consumed; the index is held so a retry gets the same key.
            # The size reported is the LARGEST this metadata can grow to, not
            # today's: `age` keeps rising, so today's length can be too small
            # by the time the application retries (seen on the live stack:
            # 18 bytes reported, 19 needed a moment later).
            most = len(json.dumps({"age": u32, "hops": 0}, separators=(",", ":")).encode())
            return _res(S.METADATA_TOO_SMALL, "T12", index=want,
                        Metadata={"Metadata_size": most, "Metadata_buffer": None})
        key_b64 = base64.b64encode(bytes(chunk.data)).decode("ascii")
        chunk.delivered = True
        chunk.erase()
        s.delivered.add(want)
        del s.chunks[want]
        transition = "T19" if s.peer_closed else "T11"
        return _res(S.SUCCESSFUL, transition, index=want, Key_buffer=key_b64,
                    Metadata={"Metadata_size": need, "Metadata_buffer": meta} if metadata_size else None)

    async def close(self, ksid: str) -> dict:
        s = self.streams.get(ksid)
        if s is None or s.state == St.CLOSED:
            raise UnknownStream(ksid)
        s.local_closed = True
        try:
            await self.peer.close(ksid, self._timeout_s(s.qos))
        except (PeerUnreachable, PeerTimeout, PeerLostStream):
            pass   # the peer's TTL sweep reclaims its side (T18)
        if s.peer_closed:
            self._to_closed(s)
            return _res(S.SUCCESSFUL, "T17")
        s.state = St.CLOSING
        return _res(S.SUCCESSFUL, "T16")

    # ------------------------------------------------------------- peer API
    async def on_announce(self, ksid: str, apps: dict, qos: dict) -> None:
        s = self.streams.get(ksid)
        if s is not None:
            if s.state == St.CLOSED or not _same_apps(s.apps, apps):
                raise ChunkConflict(ksid)
            # Both applications opened the same predefined id: the other side's
            # announce is this side's confirmation.
            s.peer_open = True
            if s.local_open:
                s.state = St.ESTABLISHED
                s.established.set()
            return
        self.streams[ksid] = Stream(ksid=ksid, apps=apps, qos=dict(qos), allocator=self.is_allocator,
                                    peer_open=True, last_activity=self.clock())

    async def on_establish(self, ksid: str) -> None:
        s = self.streams.get(ksid)
        # An application that already closed cannot be joined.
        if s is None or s.state == St.CLOSED or s.local_closed:
            raise UnknownStream(ksid)
        s.peer_open = True
        s.state = St.ESTABLISHED
        s.established.set()
        self._touch(s)

    async def on_withdraw(self, ksid: str) -> None:
        s = self.streams.get(ksid)
        if s is not None and not s.local_open:
            del self.streams[ksid]

    async def on_allocate(self, ksid: str, index: int) -> dict:
        """The non-allocator asks for chunk `index`; push it and report."""
        s = self.streams.get(ksid)
        if s is None or s.state == St.CLOSED:
            raise UnknownStream(ksid)
        if s.local_closed and index not in s.chunks:
            # This application closed: chunks already allocated are still
            # pushed, nothing new is allocated (the T19 rule, seen from here).
            return {"status": int(S.INSUFFICIENT_KEY),
                    "detail": "the peer application closed; nothing new is allocated"}
        got = await self._obtain(s, index)
        if got is None:
            return {"status": int(S.SUCCESSFUL)}
        return {"status": got["status"], "detail": got.get("detail")}

    async def on_chunk(self, ksid: str, index: int, key_ids: list[str], data_b64: str) -> None:
        s = self.streams.get(ksid)
        if s is None or s.state == St.CLOSED:
            raise UnknownStream(ksid)
        data = bytearray(base64.b64decode(data_b64))
        have = s.chunks.get(index)
        if have is not None:
            if bytes(have.data) != bytes(data):
                raise ChunkConflict(f"{ksid}#{index}")
            return   # idempotent repeat
        if index in s.delivered:
            return
        s.chunks[index] = Chunk(index=index, key_ids=list(key_ids), data=data,
                                created_at=self.clock(), confirmed_at_peer=True)
        # These keys reached this KME as 014 replicas; drop them from 014 here
        # too, so no 004 key is resolvable through dec_keys on either side.
        await self.keys.drop_replicas(list(key_ids))
        self._touch(s)

    async def on_close(self, ksid: str) -> None:
        s = self.streams.get(ksid)
        if s is None:
            raise UnknownStream(ksid)
        s.peer_closed = True
        # Closed here too once this application closed -- or never opened, in
        # which case nobody on this side can use the stream.
        if s.local_closed or not s.local_open:
            self._to_closed(s)

    # --------------------------------------------------------- allocation
    def _next_undelivered(self, s: Stream) -> int:
        i = 0
        while i in s.delivered:
            i += 1
        return i

    async def _obtain(self, s: Stream, index: int) -> dict | None:
        """Make chunk `index` available here. None on success, else a result."""
        timeout = self._timeout_s(s.qos)
        if not s.allocator:
            try:
                r = await self.peer.allocate(s.ksid, index, timeout)
            except PeerLostStream:
                self._to_closed(s)
                return _res(S.NO_QKD_CONNECTION, "T15", index=index, detail="the peer KM lost the stream")
            except PeerUnreachable:
                return _res(S.NO_QKD_CONNECTION, "T15", index=index, detail="the peer KM is unreachable")
            except PeerTimeout:
                return _res(S.TIMEOUT, "T14", index=index, detail="the peer KM did not answer within Timeout")
            if r.get("status") != int(S.SUCCESSFUL):
                return _res(S(r["status"]), "T13", index=index, detail=r.get("detail"))
            return None if index in s.chunks else _res(S.INSUFFICIENT_KEY, "T13", index=index,
                                                       detail="no chunk pushed")
        # Allocator side.
        chunk = s.chunks.get(index)
        if chunk is None:
            if index != s.next_alloc:
                return _res(S.INSUFFICIENT_KEY, "T13", index=index,
                            detail=f"chunks are allocated in order; next is {s.next_alloc}")
            m = int(s.qos["Key_chunk_size"]) // self.keys.key_bytes
            held = sum(x.held_keys() for x in self.streams.values())
            if held + m > self._cap_keys():
                return _res(S.INSUFFICIENT_KEY, "T13", index=index,
                            detail=f"004 share of the pool is full ({self._cap_keys()} keys)")
            taken = await self.keys.take_local_for_stream(m)
            if not taken:
                self.keys.request_extra(m)
                return _res(S.INSUFFICIENT_KEY, "T13", index=index,
                            detail="not enough key above the ETSI 014 floor; production requested")
            self.keys.release_extra()
            data = bytearray()
            for k in taken:
                data += base64.b64decode(k.key_b64)
            chunk = Chunk(index=index, key_ids=[k.key_id for k in taken], data=data,
                          created_at=self.clock())
            s.chunks[index] = chunk
            s.next_alloc += 1
        if not chunk.confirmed_at_peer:
            try:
                await self.peer.chunk(s.ksid, index, chunk.key_ids,
                                      base64.b64encode(bytes(chunk.data)).decode("ascii"), timeout)
            except PeerLostStream:
                self._to_closed(s)
                return _res(S.NO_QKD_CONNECTION, "T15", index=index, detail="the peer KM lost the stream")
            except PeerUnreachable:
                return _res(S.NO_QKD_CONNECTION, "T15", index=index, detail="the peer KM is unreachable")
            except PeerTimeout:
                return _res(S.TIMEOUT, "T14", index=index,
                            detail="the peer KM did not store the chunk within Timeout")
            chunk.confirmed_at_peer = True
        return None

    # --------------------------------------------------------- housekeeping
    def _to_closed(self, s: Stream) -> None:
        s.wipe()
        s.state = St.CLOSED
        s.closed_at = self.clock()

    def sweep(self) -> list[tuple[str, str]]:
        """Apply TTLs. Returns (ksid, transition) for what changed."""
        now = self.clock()
        changed: list[tuple[str, str]] = []
        for ksid, s in list(self.streams.items()):
            if s.state == St.CLOSED:
                if s.closed_at is not None and now - s.closed_at >= self.limits().max_ttl_s:
                    del self.streams[ksid]
                    changed.append((ksid, "T22"))
                continue
            ttl = self._ttl_s(s.qos)
            if now - s.last_activity >= ttl:
                self._to_closed(s)
                changed.append((ksid, "T18"))
                continue
            for i, c in list(s.chunks.items()):
                if now - c.created_at >= ttl:
                    c.erase()
                    del s.chunks[i]
                    changed.append((ksid, "T18"))
        return changed

    def state_counts(self) -> dict[str, int]:
        out = {st.value: 0 for st in St if st != St.ABSENT}
        for s in self.streams.values():
            out[s.state.value] += 1
        return out
