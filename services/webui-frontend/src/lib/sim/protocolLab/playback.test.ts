/**
 * The playback of one tick: pure, and only ever a drawing of what the engine
 * recorded. The time a key takes to cross a link on screen is not a latency.
 */
import { describe, expect, it } from "vitest";

import type { TickTrace } from "../protocolLabSim";
import { presetById } from "./publishedNetworks";
import {
  TRAVEL_SHARE, packetPose, relayProgress, stepAt, tickWindows,
} from "./playback";

const preset = presetById("tokyo-2010");
const trace = (relay: TickTrace["relay"]): TickTrace => ({
  tick: 1, t_s: 1, relay,
  steps: [
    { id: "generate", outcome: "ok", detail: "" },
    { id: "route", outcome: "ok", detail: "" },
    { id: "relay", outcome: relay ? "ok" : "idle", detail: "" },
    { id: "deliver", outcome: "ok", detail: "" },
  ],
});
const threeHops = trace({ nodes: ["K3", "K2", "O2", "HONGO"], linkIds: ["a", "b", "c"], amount: "1 key(s)" });

describe("tickWindows", () => {
  it("covers the whole tick without a gap, in stage order", () => {
    const w = tickWindows(threeHops);
    expect(w[0].start).toBe(0);
    expect(w[w.length - 1].end).toBeCloseTo(1);
    for (let i = 1; i < w.length; i++) expect(w[i].start).toBeCloseTo(w[i - 1].end);
    expect(w.map((x) => x.index)).toEqual([0, 1, 2, 3]);
  });

  it("gives relaying more of the tick the more hops it crosses", () => {
    const share = (t: TickTrace) => { const w = tickWindows(t)[2]; return w.end - w.start; };
    const oneHop = trace({ nodes: ["K3", "K2"], linkIds: ["a"], amount: "" });
    expect(share(threeHops)).toBeGreaterThan(share(oneHop));
    expect(share(oneHop)).toBeGreaterThan(share(trace(null)));
  });
});

describe("stepAt", () => {
  it("walks the stages in order and rests when the tick has played", () => {
    const w = tickWindows(threeHops);
    const seen = [0, 0.1, 0.2, 0.3, 0.5, 0.7, 0.9, 0.99].map((p) => stepAt(w, p));
    expect(seen).toEqual([...seen].sort((a, b) => (a ?? 0) - (b ?? 0)));
    expect(seen[0]).toBe(0);
    expect(seen[seen.length - 1]).toBe(3);
    expect(stepAt(w, 1)).toBeNull();
  });
});

describe("packetPose", () => {
  const node = (id: string) => preset.nodes.find((n) => n.id === id)!;

  it("starts at the source and crosses each hop along its own link", () => {
    const start = packetPose(preset, threeHops, 0)!;
    expect([start.x, start.y]).toEqual([node("K3").x, node("K3").y]);
    expect(start.hop).toBe(0);
    for (const u of [0.05, 0.1, 0.2, 0.25]) {
      const p = packetPose(preset, threeHops, u)!;
      expect(p.hop).toBe(0);
      expect(p.y).toBeCloseTo(node("K3").y);
      expect(p.x).toBeGreaterThanOrEqual(node("K3").x);
      expect(p.x).toBeLessThanOrEqual(node("K2").x);
    }
  });

  it("holds the key in the clear at a trusted node between hops, and only there", () => {
    const hopU = 1 / 3;
    const at = packetPose(preset, threeHops, hopU * (TRAVEL_SHARE + (1 - TRAVEL_SHARE) / 2))!;
    expect(at.atNode).toBe("K2");
    expect([at.x, at.y]).toEqual([node("K2").x, node("K2").y]);
    const crossing = packetPose(preset, threeHops, hopU * (TRAVEL_SHARE / 2))!;
    expect(crossing.atNode).toBeNull();
  });

  it("never calls an endpoint a trusted relay: at the far end the key has arrived", () => {
    const end = packetPose(preset, threeHops, 0.999)!;
    expect(end.atNode).toBeNull();
    expect(end.arrived).toBe(true);
    expect([end.x, end.y]).toEqual([node("HONGO").x, node("HONGO").y]);
    expect(packetPose(preset, threeHops, 0.1)!.arrived).toBe(false);
  });

  it("draws nothing when nothing crossed, or outside the relaying", () => {
    expect(packetPose(preset, trace(null), 0.5)).toBeNull();
    expect(packetPose(preset, threeHops, 1)).toBeNull();
    expect(packetPose(preset, threeHops, -0.1)).toBeNull();
    expect(packetPose(preset, trace({ nodes: ["K3"], linkIds: [], amount: "" }), 0.5)).toBeNull();
  });
});

describe("relayProgress", () => {
  const w = tickWindows(threeHops);
  const relay = w[2];

  it("runs from 0 to 1 inside the relay stage's window when the stages play", () => {
    expect(relayProgress(threeHops, w, relay.start, true)).toBeCloseTo(0);
    expect(relayProgress(threeHops, w, (relay.start + relay.end) / 2, true)).toBeCloseTo(0.5);
    expect(relayProgress(threeHops, w, relay.start - 0.01, true)).toBeNull();
    expect(relayProgress(threeHops, w, relay.end, true)).toBeNull();
  });

  it("takes the whole tick at a fast pace, where the stages do not play", () => {
    expect(relayProgress(threeHops, w, 0.25, false)).toBe(0.25);
    expect(relayProgress(threeHops, w, 1, false)).toBeNull();
    expect(relayProgress(trace(null), tickWindows(trace(null)), 0.5, false)).toBeNull();
  });
});
