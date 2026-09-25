# ETSI GS QKD 004 V2.1.1 on the KME

`bb84-kme` serves ETSI GS QKD 004 V2.1.1 (2020-08), the application interface
with `OPEN_CONNECT`, `GET_KEY` and `CLOSE`, next to the ETSI GS QKD 014 REST
API that arnika uses. The two share one key pool.

V2.1.1 defines an abstract interface: functions, parameters, QoS fields, and
status codes 0-8. **It defines no wire format.** The HTTP/JSON binding below is
this project's own, and so is every behaviour the specification leaves open;
each of those is listed in [section 7](#7-what-is-this-projects-choice). An
application written against another vendor's 004 binding will not talk to this
one unchanged.

The binding is **off by default** and off on the public demo, where nothing
drives it. The browser simulation on `/protocol-lab` does not call it.

Code: [`app/etsi004.py`](../services/bb84-kme/app/etsi004.py) (routes),
[`app/etsi004_engine.py`](../services/bb84-kme/app/etsi004_engine.py) (the
state machine), [`app/etsi004_peer.py`](../services/bb84-kme/app/etsi004_peer.py)
(the link to the peer KME). The specification's facts -- names, types, units,
codes, and the transition table -- live in one file,
[`etsi004SpecV211.json`](../services/webui-frontend/src/lib/sim/etsi004SpecV211.json),
which the browser simulator also imports and the KME image copies in.

---

## 1. Switching it on

```yaml
# config/qkd_params.yaml
etsi004:
  endpoint_enabled: true
```

The file is hot-reloaded, so no restart is needed. While it is `false`, every
route below answers HTTP 404. The CI `live-stack` job switches it on and runs
[`tests/test_etsi004_contract.py`](../tests/test_etsi004_contract.py) against
two live KMEs, next to the ETSI 014 contract.

The other keys in the section:

| Key | Shipped | Meaning |
|---|---|---|
| `max_streams` | 8 | Open streams per KME. One more is status 4. |
| `max_pool_share` | 0.25 | Undelivered 004 chunks may hold at most this share of the pool, $`\lfloor s \cdot C \rfloor`$ keys: 16 of $`C = 64`$. |
| `default_timeout_ms` / `max_timeout_ms` | 5000 / 30000 | QoS `Timeout` when none is sent, and the most a caller may ask for. |
| `default_ttl_s` / `max_ttl_s` | 60 / 3600 | QoS `TTL` when none is sent, and the most a caller may ask for. `max_ttl_s` is also how long a closed `Key_stream_ID` stays refused. |
| `sweep_interval_s` | 1.0 | How often TTLs are applied. |

The share is checked at start and on every call. With $`w`$ the ETSI 014
watermark (`simulator.pool_low_watermark`), it must satisfy

```math
2w + \lfloor s \cdot C \rfloor \;\le\; C
```

so that this KME's 014 floor, the peer's replicas and the 004 chunks all fit in
one ring buffer. A value that breaks it fails loudly instead of letting the
buffer evict keys the other KME still needs.

## 2. Routes

All three are `POST` with a JSON body, under `/etsi004/v2.1.1`. Unknown fields
are rejected, every integer is checked against the uint32 range, and a
`Key_stream_ID` must be a UUID.

**`open_connect`**

```json
{"source": "sae://alice/app", "destination": "sae://bob/app",
 "QoS": {"Key_chunk_size": 32, "Timeout": 5000, "TTL": 60},
 "Key_stream_ID": null}
```

`source` and `destination` are URIs. `QoS` and `Key_stream_ID` may be omitted.
The answer carries `status`, `Key_stream_ID` and the QoS as registered, which
is what the KME will actually honour.

**`get_key`**

```json
{"Key_stream_ID": "...", "index": null, "Metadata": {"Metadata_size": 64}}
```

The answer carries `status`, `index`, `Key_buffer` (base64), and `Metadata`
with `Metadata_size` and `Metadata_buffer` when a non-zero size was sent.

**`close`**

```json
{"Key_stream_ID": "..."}
```

Every response also carries `transition`, the id of the rule in the spec file
that answered (`T1` to `T22`), and sometimes `detail`, a sentence saying why.
Neither is part of V2.1.1; both are there so a caller can tell apart two
answers with the same status.

### Units

| Field | Unit | Note |
|---|---|---|
| `Key_chunk_size` | **bytes** | ETSI GS QKD 014 sizes keys in **bits**. A chunk is a whole number of produced keys (32 bytes each here); anything else is status 7 with the nearest whole size offered. `null` or 0 means one key. |
| `Max_bps`, `Min_bps`, `Jitter` | bit/s | `Min_bps` is checked against the MEASURED production rate minus what other open streams reserved -- never against the modelled key rate, which is orders of magnitude higher than what the simulator emits. |
| `Timeout` | ms | Clamped to `max_timeout_ms`. |
| `TTL` | s | Clamped to `max_ttl_s`. |
| `age` (metadata) | ms | Since the chunk became available on this KME. |

## 3. HTTP status and 004 status

| HTTP | When |
|---|---|
| 200 | Every protocol outcome. The 004 `status` is in the body. |
| 422 | A malformed request: bad UUID, a value outside uint32, an unknown field, a missing `source`. |
| 404 | A `Key_stream_ID` this KME does not know, one that is closed, or one this application already closed; and every route while the binding is off. |

The 004 status codes are V2.1.1's; the names in
[`etsi004_spec.py`](../services/bb84-kme/app/etsi004_spec.py) are this
project's.

| Code | Meaning | Returned here when |
|---|---|---|
| 0 | Successful | The call did what was asked. |
| 1 | Peer not connected | `open_connect` without a `Key_stream_ID`: the stream is registered at both KMEs and waits for the peer application (T1). |
| 2 | Insufficient key | No chunk can be supplied now (T13), the index was already read on this side (T21), or the peer closed and no chunk for that index was allocated (T19). |
| 3 | Peer application not connected | `get_key` before the peer application opened the stream (T10). |
| 4 | No QKD connection | The peer KME is unreachable (T3, T15), no longer knows the stream (T15), or the stream limit is reached (T4). |
| 5 | Key_stream_ID in use | Held by another application pair (T7), already opened at this KME (T8), or closed (T9). |
| 6 | Timeout | The peer KME did not answer within `Timeout` (T14), or a predefined `Key_stream_ID` was not opened by the peer application within it (T6). |
| 7 | QoS not met | The registered QoS in the answer is the nearest this KME can honour (T2). |
| 8 | Metadata too small | `Metadata_size` is non-zero and too small (T12). Nothing is consumed; see below. |

## 4. How both KMEs end up with the same bytes

1. **One KME allocates.** The KME whose SAE_ID sorts first (ALICE) creates
   every chunk; the other asks it to (`/internal/etsi004/allocate`) and receives
   the chunk by push (`/internal/etsi004/chunk`).
2. **A chunk never changes.** A repeated push of the same bytes is accepted; a
   push of different bytes for an index already stored is HTTP 409.
3. **Nothing is delivered before the peer has it.** The allocator hands chunk
   $`i`$ to its own application only after the peer confirmed storing it. If
   the peer does not confirm within `Timeout`, the answer is status 6 and the
   chunk is kept for the retry.
4. **Each side reads a chunk once**, then erases it.
5. **No lock is held across a call to the peer.** The peer's allocate handler
   calls back with a push; a lock held across that would deadlock.

## 5. Sharing the pool with ETSI GS QKD 014

arnika's `enc_keys` must never be starved by a 004 stream.

- A chunk is taken only if at least $`w`$ locally produced keys remain for
  014 afterwards (the **014 floor**). Short of that, `get_key` answers status 2
  at once and asks the producer for more: its gate rises by one chunk's worth
  of keys (at most $`C - 2w`$) and drops back once the chunk is made. With no
  004 demand the gate is exactly what it was before 004 existed.
- Undelivered chunks at the allocator hold at most the share in section 1.
- Keys moved into a chunk leave the 014 index **on both KMEs**: the allocator
  removes them when it takes them, the peer drops its replicas when the chunk
  arrives, and a replica that arrives after its chunk is refused. No 004 key
  can be fetched through 014 `dec_keys`.

## 6. Metadata

`Metadata_buffer` is JSON, `{"age": <ms>, "hops": 0}`, the two keys of Table 3.
`hops` is always 0: the two KMEs share a direct simulated link.

`age` grows while an application reallocates its buffer, so the size needed
grows too. A status 8 answer therefore reports the **largest** size this
metadata can reach -- with `age` at the uint32 maximum -- not the size at that
moment. A retry with the reported size always succeeds and gets the same key
at the same index. (The first version reported the size at that moment; the
live contract test caught the retry failing when `age` gained a digit.)

## 7. What is this project's choice

V2.1.1 is silent on these, so each is a decision, recorded with its reason in
the spec file's transition table:

- The binding: routes, JSON field spelling, HTTP 404 for an unknown or closed
  stream (V2.1.1 has no code for it, and a vendor code would break the 0-8
  range), 422 for a malformed request.
- `index` starts at 0: Table 2 places a key at index times `Key_chunk_size`.
  `null` means the next index not yet read on this side. An index ahead of the
  allocation order is status 2, not a skip.
- `get_key` with no key available returns status 2 immediately and requests
  production, rather than waiting up to `Timeout`: a waiting request would
  hold the worker that also serves ETSI 014.
- Status 4 for the stream limit (V2.1.1 has no resource-limit code).
- Status 7 counter-proposes the nearest QoS: whole keys for `Key_chunk_size`,
  the measured rate for `Min_bps`, `application/json` for the mimetype.
- A predefined `Key_stream_ID` that times out is rolled back on both KMEs.
- A closed `Key_stream_ID` is not reused while its record is kept
  (`max_ttl_s`).
- `TTL` is measured from the last activity on the stream, and from its
  allocation for a single chunk.
- After the peer closes, chunks already allocated can still be read; nothing
  new is allocated.
- `Priority` and `Jitter` are registered and echoed, not enforced.
- `Key_stream_ID` may be any UUID version.

## 8. Limits

- **No authentication.** Like ETSI 014 on this stack and `/internal/sync`, the
  binding is reachable only on the internal compose networks: no KME port is
  published, the frontend proxies only `/api/`, and webui-backend has no route
  that reaches it (`tests/test_the_004_binding_is_not_public.py`). mTLS is not
  implemented.
- **In memory, one worker.** Streams live in the KME process; a restart
  forgets them, and the peer then closes its side on the next call (T15). Run
  the KME as a single uvicorn worker.
- **Zeroization is best effort.** Chunks are `bytearray`s cleared after
  delivery and on close, but CPython cannot guarantee that no copy of key bytes
  made along the way survives in memory.
- **Point to point.** Two KMEs, one hop. The trusted-node relay on
  `/protocol-lab` is a simulation and does not use this endpoint.
- Edition 3 of GS QKD 004 (V3.1.1, a stable draft dated 2026-05-23 and
  unpublished on 2026-09-25) renumbers the status codes. Nothing here mixes the
  two editions.

## 9. Tests

| File | What it holds |
|---|---|
| [`test_etsi004_state_machine.py`](../tests/test_etsi004_state_machine.py) | Two engines in memory on real key pools: every endpoint transition in the spec file is exercised, both sides read identical bytes, nothing is delivered before the peer stored it, the 014 floor and the share hold, no 004 key resolves through 014. |
| [`test_etsi004_http_binding.py`](../tests/test_etsi004_http_binding.py) | The same through the real routes and peer link, in-process: 404 while off, 422, 404 for an unknown stream, 409 for a conflicting chunk, peer routes kept out of the schema. |
| [`test_etsi004_contract.py`](../tests/test_etsi004_contract.py) | Two live KMEs (CI `live-stack`): statuses 0, 1, 2, 3, 5, 7 and 8, a predefined id, TTL, and ETSI 014 still served while a 004 stream drains the pool. |
| [`test_etsi004_spec_is_v2_1_1.py`](../tests/test_etsi004_spec_is_v2_1_1.py), [`test_protocol_lab_etsi_spec.py`](../tests/test_protocol_lab_etsi_spec.py) | The spec file is V2.1.1, the KME reads it through `ETSI004_SPEC_FILE` only, the image carries it, and the browser simulator imports the same file. |
| [`test_the_004_binding_is_not_public.py`](../tests/test_the_004_binding_is_not_public.py), [`test_every_etsi004_key_is_read_by_the_kme.py`](../tests/test_every_etsi004_key_is_read_by_the_kme.py) | Not exposed, off in the shipped config, and every config key read by the KME. |
