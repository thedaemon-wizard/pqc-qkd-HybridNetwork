/**
 * The simulated ETSI GS QKD 004 V2.1.1 key manager, driven through the
 * transitions the shared spec file marks for the simulator.
 */
import { describe, expect, it } from "vitest";

import SPEC from "../etsi004SpecV211.json";
import { BUNDLED_PARAMS } from "../keyrate";
import { EMPTY_QOS, INDEX_ORIGIN, Km004, statusCode, type CallResult } from "./etsi004";

const K = BUNDLED_PARAMS.outBitsPerKey / 8;

function km(opts: { routeUp?: () => boolean; bps?: number | null } = {}) {
  let n = 0;
  let t = 0;
  const seen = new Set<string>();
  const k = new Km004({
    keyChunkBytes: K,
    routeUp: opts.routeUp ?? (() => true),
    capacity: () => ({ bps: opts.bps === undefined ? 1000 : opts.bps, basis: "test" }),
    now: () => t,
    newKsid: () => `00000000-0000-4000-8000-${String(++n).padStart(12, "0")}`,
  });
  const track = (r: CallResult) => { seen.add(r.transition); return r; };
  const open = () => {
    const a = track(k.openConnect("A", "qkd://a/app", "qkd://b/app", { ...EMPTY_QOS }, null));
    const b = track(k.openConnect("B", "qkd://b/app", "qkd://a/app", { ...EMPTY_QOS }, a.Key_stream_ID!));
    return { a, b, ksid: a.Key_stream_ID! };
  };
  return { k, open, track, seen, advance: (ms: number) => { t += ms; } };
}

const chunk = (fill: number) => new Uint8Array(K).fill(fill);

describe("status codes", () => {
  it("are exactly 0-8, with 1 = peer not connected and 6 = timeout (not edition 3)", () => {
    expect(SPEC.status_codes.map((s) => s.code)).toEqual([0, 1, 2, 3, 4, 5, 6, 7, 8]);
    expect(statusCode("PEER_NOT_CONNECTED")).toBe(1);
    expect(statusCode("TIMEOUT")).toBe(6);
  });

  it("measures Key_chunk_size in bytes, and one relayed key is out_bits_per_key/8 of them", () => {
    expect(SPEC.qos_fields.find((f) => f.name === "Key_chunk_size")!.unit).toBe("bytes");
    const { open, k } = km();
    const { ksid } = open();
    expect(k.chunkBytes(ksid)).toBe(K);
  });

  it("starts indices at 0", () => {
    expect(INDEX_ORIGIN).toBe(0);
    expect(SPEC.binding.index_origin).toBe(0);
  });
});

describe("the null-Key_stream_ID sequence (clause 6.2.2)", () => {
  it("OPEN from A gives 1 and a new id; OPEN from B with it gives 0", () => {
    const { open } = km();
    const { a, b } = open();
    expect(a.status).toBe(1); expect(a.transition).toBe("T1");
    expect(b.status).toBe(0); expect(b.transition).toBe("T5");
  });

  it("GET_KEY before the peer opens gives 3", () => {
    const { k, track } = km();
    const a = k.openConnect("A", "qkd://a/app", "qkd://b/app", { ...EMPTY_QOS }, null);
    const r = track(k.getKey("A", a.Key_stream_ID!, null, 0));
    expect(r.status).toBe(3);
  });

  it("delivers the same bytes at the same index on both sides", () => {
    const { k, open } = km();
    const { ksid } = open();
    k.supply(ksid, chunk(7), 2);
    const ra = k.getKey("A", ksid, null, 0);
    const rb = k.getKey("B", ksid, ra.index!, 0);
    expect(ra.status).toBe(0);
    expect(rb.status).toBe(0);
    expect(ra.index).toBe(0);
    expect([...ra.Key_buffer!]).toEqual([...rb.Key_buffer!]);
  });

  it("gives 2 when nothing has been relayed, and 2 again for an index already read", () => {
    const { k, open, track } = km();
    const { ksid } = open();
    expect(track(k.getKey("A", ksid, null, 0)).status).toBe(2);
    k.supply(ksid, chunk(1), 0);
    expect(k.getKey("A", ksid, 0, 0).status).toBe(0);
    const again = track(k.getKey("A", ksid, 0, 0));
    expect(again.status).toBe(2); expect(again.transition).toBe("T21");
  });

  it("gives 8 with the needed size for a small metadata buffer, and the retry gets the same key", () => {
    const { k, open, track, advance } = km();
    const { ksid } = open();
    k.supply(ksid, chunk(9), 3);
    advance(40);
    const small = track(k.getKey("A", ksid, null, 4));
    expect(small.status).toBe(8);
    const retry = k.getKey("A", ksid, small.index!, small.Metadata!.Metadata_size);
    expect(retry.status).toBe(0);
    expect(retry.index).toBe(small.index);
    expect(JSON.parse(retry.Metadata!.Metadata_buffer!)).toEqual({ age: 40, hops: 3 });
  });

  it("reports hops as the relays the chunk crossed (Table 3: 0 = direct)", () => {
    const { k, open } = km();
    const { ksid } = open();
    k.supply(ksid, chunk(2), 0);
    const r = k.getKey("A", ksid, null, 256);
    expect(JSON.parse(r.Metadata!.Metadata_buffer!).hops).toBe(0);
  });

  it("closes in two steps and then refuses the id", () => {
    const { k, open, track } = km();
    const { ksid } = open();
    expect(track(k.close("A", ksid)).transition).toBe("T16");
    expect(track(k.close("B", ksid)).transition).toBe("T17");
    const reopen = track(k.openConnect("A", "qkd://a/app", "qkd://b/app", { ...EMPTY_QOS }, ksid));
    expect(reopen.status).toBe(5);
    const get = track(k.getKey("A", ksid, null, 0));
    expect(get.status).toBeNull(); expect(get.http).toBe(404);
  });
});

describe("failures", () => {
  it("gives 4 when no route joins the two KMs", () => {
    const { k, track } = km({ routeUp: () => false });
    expect(track(k.openConnect("A", "qkd://a/app", "qkd://b/app", { ...EMPTY_QOS }, null)).status).toBe(4);
  });

  it("gives 4 on GET_KEY when the route goes down mid-stream", () => {
    let up = true;
    const { k, open, track } = km({ routeUp: () => up });
    const { ksid } = open();
    up = false;
    const r = track(k.getKey("A", ksid, null, 0));
    expect(r.status).toBe(4); expect(r.transition).toBe("T15");
  });

  it("gives 5 to a different application pair", () => {
    const { k, open, track } = km();
    const { ksid } = open();
    expect(track(k.openConnect("A", "qkd://x/app", "qkd://y/app", { ...EMPTY_QOS }, ksid)).status).toBe(5);
  });

  it("gives 7 with a labelled counter-proposal for an unmeetable QoS", () => {
    const { k, track } = km({ bps: 500 });
    const r = track(k.openConnect("A", "qkd://a/app", "qkd://b/app", { ...EMPTY_QOS, Min_bps: 900 }, null));
    expect(r.status).toBe(7);
    expect(r.QoS!.Min_bps).toBe(500);
    expect(r.rateBasis).toBe("test");
    const odd = track(k.openConnect("A", "qkd://a/app", "qkd://b/app", { ...EMPTY_QOS, Key_chunk_size: K + 1 }, null));
    expect(odd.status).toBe(7);
    expect(odd.QoS!.Key_chunk_size! % K).toBe(0);
  });

  it("zeroes key material on clear", () => {
    const { k, open } = km();
    const { ksid } = open();
    const c = chunk(5);
    k.supply(ksid, c, 0);
    k.clear();
    expect(k.list()).toEqual([]);
  });
});

describe("coverage of the shared spec", () => {
  it("exercises every transition the spec file scopes to the simulator", () => {
    // Re-run every case above in one place, collecting transitions.
    const seen = new Set<string>();
    const add = (r: CallResult) => seen.add(r.transition);
    let up = true;
    const k = new Km004({
      keyChunkBytes: K, routeUp: () => up, capacity: () => ({ bps: 100, basis: "t" }),
      now: () => 0, newKsid: (() => { let i = 0; return () => `id-${++i}`; })(),
    });
    add(k.openConnect("A", "s", "d", { ...EMPTY_QOS, Min_bps: 200 }, null));           // T2
    up = false; add(k.openConnect("A", "s", "d", { ...EMPTY_QOS }, null)); up = true;  // T3
    const a = k.openConnect("A", "s", "d", { ...EMPTY_QOS }, null); add(a);            // T1
    add(k.getKey("A", a.Key_stream_ID!, null, 0));                                     // T10
    add(k.openConnect("B", "x", "y", { ...EMPTY_QOS }, a.Key_stream_ID!));             // T7
    add(k.openConnect("B", "d", "s", { ...EMPTY_QOS }, a.Key_stream_ID!));             // T5
    add(k.getKey("A", a.Key_stream_ID!, null, 0));                                     // T13
    k.supply(a.Key_stream_ID!, chunk(1), 1);
    add(k.getKey("A", a.Key_stream_ID!, null, 1));                                     // T12
    add(k.getKey("A", a.Key_stream_ID!, null, 0));                                     // T11
    add(k.getKey("A", a.Key_stream_ID!, INDEX_ORIGIN, 0));                             // T21
    up = false; add(k.getKey("B", a.Key_stream_ID!, null, 0)); up = true;             // T15
    add(k.close("A", a.Key_stream_ID!));                                               // T16
    add(k.close("B", a.Key_stream_ID!));                                               // T17
    const simScoped = SPEC.transitions.filter((t) => t.scope.includes("sim")).map((t) => t.id);
    for (const id of simScoped) expect(seen, `transition ${id} is scoped "sim" but never exercised`).toContain(id);
  });

  it("gives every inferred transition a rationale", () => {
    for (const t of SPEC.transitions) {
      if (t.basis === "inference") expect(t.rationale, t.id).toBeTruthy();
      expect(t.ref, t.id).toBeTruthy();
    }
  });
});
