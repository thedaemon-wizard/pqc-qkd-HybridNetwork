/**
 * A simulated ETSI GS QKD 004 V2.1.1 key manager pair, for /protocol-lab.
 *
 * Both ends of one end-to-end association live in this object: application A
 * talks to KM A, application B to KM B, and the relay in protocolLabSim.ts
 * puts identical chunks into both. Nothing here touches a network.
 *
 * Status codes, QoS units and the transition table come from
 * `../etsi004SpecV211.json`, the same file the KME's real endpoint loads
 * (services/bb84-kme/app/etsi004_spec.py). Every call reports which
 * transition it took, so the tests can check that each transition the spec
 * file marks `scope: "sim"` is exercised here, and the timeline can show it.
 *
 * Index origin 0, and `null` means "the KM chooses the next index this side
 * has not received" -- the binding section of the spec file, with its reason.
 */
import SPEC from "../etsi004SpecV211.json";

export type StatusId =
  | "SUCCESSFUL" | "PEER_NOT_CONNECTED" | "INSUFFICIENT_KEY" | "PEER_APP_NOT_CONNECTED"
  | "NO_QKD_CONNECTION" | "KSID_IN_USE" | "TIMEOUT" | "QOS_NOT_MET" | "METADATA_TOO_SMALL";

/** The numeric code for a status id, read from the spec file. */
export function statusCode(id: StatusId): number {
  const s = SPEC.status_codes.find((x) => x.id === id);
  if (!s) throw new Error(`status ${id} is not in the spec file`);
  return s.code;
}

export function statusById(code: number): { code: number; id: string; paraphrase: string; ref: string } {
  const s = SPEC.status_codes.find((x) => x.code === code);
  if (!s) throw new Error(`status code ${code} is not in V2.1.1`);
  return s;
}

export const SPEC_VERSION = `${SPEC.standard} ${SPEC.version}`;
export const INDEX_ORIGIN: number = SPEC.binding.index_origin;

export type Side = "A" | "B";
const other = (s: Side): Side => (s === "A" ? "B" : "A");

export interface QoS {
  Key_chunk_size: number | null;
  Max_bps: number | null;
  Min_bps: number | null;
  Jitter: number | null;
  Priority: number | null;
  Timeout: number | null;
  TTL: number | null;
  Metadata_mimetype: string | null;
}

export const EMPTY_QOS: QoS = {
  Key_chunk_size: null, Max_bps: null, Min_bps: null, Jitter: null,
  Priority: null, Timeout: null, TTL: null, Metadata_mimetype: null,
};

type StreamState = "PENDING_PEER" | "ESTABLISHED" | "CLOSING" | "CLOSED";

interface Stream {
  ksid: string;
  apps: { source: string; destination: string };
  qos: QoS;
  opened: Record<Side, boolean>;
  closed: Record<Side, boolean>;
  state: StreamState;
  chunks: { data: Uint8Array; availableAt: number; hops: number }[];
  delivered: Record<Side, Set<number>>;
}

export interface CallResult {
  /** The 004 status, or null where the binding answers at the HTTP layer. */
  status: number | null;
  /** Set where this project's binding answers with an HTTP status instead (T20). */
  http?: number;
  transition: string;
  Key_stream_ID?: string | null;
  QoS?: QoS;
  index?: number | null;
  Key_buffer?: Uint8Array | null;
  Metadata?: { Metadata_size: number; Metadata_buffer: string | null };
  detail?: string;
  /** Where a counter-proposed rate came from, so the page can label it. */
  rateBasis?: string;
}

export interface Km004Env {
  /** Bytes one relayed key yields: out_bits_per_key / 8 from config. */
  keyChunkBytes: number;
  /** True while at least one route of working links joins the two KMs. */
  routeUp: () => boolean;
  /** The route's bottleneck rate in bit/s, and what it is based on. */
  capacity: () => { bps: number | null; basis: string };
  /** Simulated time in ms. */
  now: () => number;
  /** Generates a Key_stream_ID. crypto.randomUUID in the page. */
  newKsid: () => string;
}

/** Same application pair, in either orientation. */
function sameApps(a: { source: string; destination: string }, b: { source: string; destination: string }) {
  return (a.source === b.source && a.destination === b.destination)
    || (a.source === b.destination && a.destination === b.source);
}

export class Km004 {
  private streams = new Map<string, Stream>();
  private readonly env: Km004Env;

  constructor(env: Km004Env) { this.env = env; }

  /** Streams with their state, for the page. */
  list(): { ksid: string; state: StreamState; chunks: number; delivered: Record<Side, number> }[] {
    return [...this.streams.values()].map((s) => ({
      ksid: s.ksid, state: s.state, chunks: s.chunks.length,
      delivered: { A: s.delivered.A.size, B: s.delivered.B.size },
    }));
  }

  /** Chunk size in bytes the stream was opened with. */
  chunkBytes(ksid: string): number | null {
    return this.streams.get(ksid)?.qos.Key_chunk_size ?? null;
  }

  isEstablished(ksid: string | null): boolean {
    return ksid !== null && this.streams.get(ksid)?.state === "ESTABLISHED";
  }

  openConnect(side: Side, source: string, destination: string, qosIn: QoS,
              ksid: string | null): CallResult {
    if (ksid !== null) {
      const s = this.streams.get(ksid);
      if (!s) {
        return { status: null, transition: "T6", Key_stream_ID: ksid,
                 detail: "not simulated: predefined Key_stream_IDs (clause 6.2.4) block until the peer opens; only the null-KSID sequence of clause 6.2.2 is modelled here" };
      }
      if (!sameApps(s.apps, { source, destination })) {
        return { status: statusCode("KSID_IN_USE"), transition: "T7", Key_stream_ID: ksid,
                 detail: "Key_stream_ID belongs to another application pair" };
      }
      if (s.state === "CLOSED") {
        return { status: statusCode("KSID_IN_USE"), transition: "T9", Key_stream_ID: ksid,
                 detail: "a closed Key_stream_ID is not reused" };
      }
      if (s.opened[side]) {
        return { status: statusCode("KSID_IN_USE"), transition: "T8", Key_stream_ID: ksid,
                 detail: "this side already opened the stream" };
      }
      // The registered QoS is returned whatever was asked (NOTE under the
      // interface syntax).
      s.opened[side] = true;
      s.state = "ESTABLISHED";
      return { status: statusCode("SUCCESSFUL"), transition: "T5", Key_stream_ID: ksid, QoS: { ...s.qos } };
    }

    if (!this.env.routeUp()) {
      return { status: statusCode("NO_QKD_CONNECTION"), transition: "T3", Key_stream_ID: null,
               detail: "no route of working QKD links between the two KMs" };
    }

    const k = this.env.keyChunkBytes;
    const asked = qosIn.Key_chunk_size;
    const counter: QoS = { ...EMPTY_QOS, ...qosIn, Key_chunk_size: asked && asked > 0 ? asked : k };
    let unmet: string | null = null;
    if (asked && asked > 0 && asked % k !== 0) {
      counter.Key_chunk_size = Math.max(k, Math.round(asked / k) * k);
      unmet = `Key_chunk_size must be a multiple of ${k} bytes (one relayed key)`;
    }
    const cap = this.env.capacity();
    if (qosIn.Min_bps !== null && qosIn.Min_bps > 0 && cap.bps !== null && qosIn.Min_bps > cap.bps) {
      counter.Min_bps = Math.floor(cap.bps);
      unmet = unmet ?? `Min_bps above the route's bottleneck rate (${cap.basis})`;
    }
    if (qosIn.Metadata_mimetype && qosIn.Metadata_mimetype !== SPEC.binding.preferred_metadata_mimetype) {
      counter.Metadata_mimetype = SPEC.binding.preferred_metadata_mimetype;
      unmet = unmet ?? "only application/json metadata is supported";
    }
    if (unmet) {
      return { status: statusCode("QOS_NOT_MET"), transition: "T2", Key_stream_ID: null,
               QoS: counter, detail: unmet, rateBasis: cap.basis };
    }

    const id = this.env.newKsid();
    this.streams.set(id, {
      ksid: id, apps: { source, destination }, qos: counter,
      opened: { A: side === "A", B: side === "B" }, closed: { A: false, B: false },
      state: "PENDING_PEER", chunks: [], delivered: { A: new Set(), B: new Set() },
    });
    return { status: statusCode("PEER_NOT_CONNECTED"), transition: "T1", Key_stream_ID: id, QoS: { ...counter } };
  }

  /** The relay hands both KMs one chunk; identical bytes on both sides by construction. */
  supply(ksid: string, data: Uint8Array, hops: number): number | null {
    const s = this.streams.get(ksid);
    if (!s || s.state !== "ESTABLISHED") return null;
    s.chunks.push({ data: data.slice(), availableAt: this.env.now(), hops });
    return INDEX_ORIGIN + s.chunks.length - 1;
  }

  /** Chunks relayed but not yet read by this side. */
  undelivered(ksid: string, side: Side): number {
    const s = this.streams.get(ksid);
    return s ? s.chunks.length - s.delivered[side].size : 0;
  }

  getKey(side: Side, ksid: string, index: number | null, metadataSize: number): CallResult {
    const s = this.streams.get(ksid);
    if (!s || s.state === "CLOSED") {
      return { status: null, http: SPEC.binding.unknown_ksid_http, transition: "T20", index: null,
               detail: "unknown or closed Key_stream_ID" };
    }
    if (s.state === "PENDING_PEER") {
      return { status: statusCode("PEER_APP_NOT_CONNECTED"), transition: "T10", index: null };
    }
    if (!this.env.routeUp()) {
      return { status: statusCode("NO_QKD_CONNECTION"), transition: "T15", index: null,
               detail: "the route between the two KMs has no working link" };
    }
    const want = index ?? this.nextFor(s, side);
    const slot = want - INDEX_ORIGIN;
    if (s.delivered[side].has(want)) {
      return { status: statusCode("INSUFFICIENT_KEY"), transition: "T21", index: want,
               detail: "that index was already delivered to this side and erased" };
    }
    const chunk = s.chunks[slot];
    if (!chunk) {
      return { status: statusCode("INSUFFICIENT_KEY"), transition: "T13", index: want,
               detail: "no chunk relayed for this index yet" };
    }
    const meta = JSON.stringify({ age: Math.max(0, Math.round(this.env.now() - chunk.availableAt)), hops: chunk.hops });
    const needed = new TextEncoder().encode(meta).length;
    if (metadataSize > 0 && metadataSize < needed) {
      // Nothing consumed; the index is held so the retry gets the same key.
      return { status: statusCode("METADATA_TOO_SMALL"), transition: "T12", index: want,
               Metadata: { Metadata_size: needed, Metadata_buffer: null } };
    }
    s.delivered[side].add(want);
    return {
      status: statusCode("SUCCESSFUL"), transition: "T11", index: want,
      Key_buffer: chunk.data.slice(),
      Metadata: metadataSize > 0 ? { Metadata_size: needed, Metadata_buffer: meta } : undefined,
    };
  }

  close(side: Side, ksid: string): CallResult {
    const s = this.streams.get(ksid);
    if (!s) {
      return { status: null, http: SPEC.binding.unknown_ksid_http, transition: "T20",
               detail: "unknown Key_stream_ID" };
    }
    if (s.state === "CLOSED") {
      // Idempotent: closing a closed stream succeeds (T20).
      return { status: statusCode("SUCCESSFUL"), transition: "T20", detail: "already closed" };
    }
    s.closed[side] = true;
    if (s.closed[other(side)]) {
      // Kept as a closed record so the Key_stream_ID is not reused (T9).
      s.state = "CLOSED";
      for (const c of s.chunks) c.data.fill(0);
      s.chunks = [];
      return { status: statusCode("SUCCESSFUL"), transition: "T17" };
    }
    s.state = "CLOSING";
    return { status: statusCode("SUCCESSFUL"), transition: "T16" };
  }

  /** Wipe every stream's key material. */
  clear(): void {
    for (const s of this.streams.values()) for (const c of s.chunks) c.data.fill(0);
    this.streams.clear();
  }

  private nextFor(s: Stream, side: Side): number {
    let i = INDEX_ORIGIN;
    while (s.delivered[side].has(i)) i += 1;
    return i;
  }
}
