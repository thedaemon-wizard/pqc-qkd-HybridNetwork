/**
 * Route selection: enumeration, ranking, and what happens to unknown values.
 */
import { describe, expect, it } from "vitest";

import { presetById } from "./publishedNetworks";
import { rankRoutes, routeKey, selectRoute, simplePaths, type LinkView, type RouteChoice } from "./routing";

const secoqc = presetById("secoqc-vienna-2008");
const G = { nodes: secoqc.nodes.map((n) => n.id), links: secoqc.links };
const up = (bits: Record<string, number | null> = {}): ((id: string) => LinkView) =>
  (id) => ({ up: true, usable: true, availableBits: id in bits ? bits[id] : 1, rateBps: 1 });

describe("simple paths", () => {
  it("finds SECOQC's five FOR-to-BRT routes (section 5.1.2: 'five possible routes')", () => {
    expect(simplePaths(G, "FOR", "BRT")).toHaveLength(5);
  });

  it("drops paths through a down link or node", () => {
    expect(simplePaths(G, "FOR", "BRT", { nodes: new Set(), links: new Set(["SIE-GUD"]) })).toHaveLength(3);
    expect(simplePaths(G, "FOR", "BRT", { nodes: new Set(["ERD"]), links: new Set() })).toHaveLength(0);
  });
});

describe("ranking", () => {
  const MiB = 8 * 1_048_576;
  // SECOQC at t = 0 of the replay, in MiB above the 2 MiB threshold.
  const bits = { "ERD-FOR": 10 * MiB, "ERD-BRT": 3.5 * MiB, "SIE-ERD": 4.6 * MiB,
                 "SIE-BRT": 4 * MiB, "ERD-GUD": 1.8 * MiB, "BRT-GUD": 2.9 * MiB };

  it("picks route 1 (fewest hops) where pure widest-bottleneck would pick route 2", () => {
    const sel = selectRoute(G, "FOR", "BRT", up(bits));
    expect(sel.chosen!.nodes).toEqual(["FOR", "ERD", "BRT"]);
    const widest = [...sel.ranked].sort((a, b) => (b.bottleneckBits ?? 0) - (a.bottleneckBits ?? 0))[0];
    expect(widest.nodes).toEqual(["FOR", "ERD", "SIE", "BRT"]);
  });

  it("ranks an unknown bottleneck below every known one", () => {
    const a: RouteChoice = { nodes: ["A", "B"], linkIds: ["x"], hops: 1, relays: 0, bottleneckBits: null, bottleneckBps: null };
    const b: RouteChoice = { nodes: ["A", "C"], linkIds: ["y"], hops: 1, relays: 0, bottleneckBits: 0, bottleneckBps: 0 };
    expect(rankRoutes([a, b])[0]).toBe(b);
  });

  it("makes one unknown hop make the whole bottleneck unknown", () => {
    const sel = selectRoute(G, "FOR", "BRT", up({ "ERD-BRT": null }));
    const r1 = sel.ranked.find((r) => routeKey(r.nodes) === "FOR-ERD-BRT")!;
    expect(r1.bottleneckBits).toBeNull();
  });

  it("reports why each unusable route was rejected", () => {
    const sel = selectRoute(G, "FOR", "BRT", (id) =>
      id === "ERD-BRT" ? { up: true, usable: false, why: "store at its minimum threshold", availableBits: 0, rateBps: 1 }
        : { up: true, usable: true, availableBits: 1, rateBps: 1 });
    expect(sel.rejected.map((r) => r.why)).toContain("ERD-BRT: store at its minimum threshold");
    expect(sel.chosen!.nodes).not.toEqual(["FOR", "ERD", "BRT"]);
  });

  it("honours a preferred route while it is usable", () => {
    const tok = presetById("tokyo-2010");
    const g = { nodes: tok.nodes.map((n) => n.id), links: tok.links };
    const sel = selectRoute(g, "K1", "O2", up(), { preferred: ["K1", "O1", "O2"] });
    expect(sel.chosen!.nodes).toEqual(["K1", "O1", "O2"]);
  });

  it("says why there is no route at all", () => {
    expect(selectRoute(G, "FOR", "BRT", up(), { downNodes: new Set(["BRT"]) }).none).toMatch(/endpoint BRT is down/);
    const allDown = selectRoute(G, "FOR", "BRT", () => ({ up: false, usable: false, availableBits: null, rateBps: null }));
    expect(allDown.chosen).toBeNull();
    expect(allDown.none).toMatch(/no path/);
  });
});
