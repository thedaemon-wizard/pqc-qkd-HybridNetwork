/**
 * The engine says what each tick did, part by part, so the page can draw it
 * rather than guess it from two snapshots; and the speed the page runs at
 * changes how fast it is drawn, and nothing it computes.
 */
import { afterAll, beforeAll, describe, expect, it } from "vitest";

import { DEFAULT_PRESET_ID, PRESETS } from "./protocolLab/publishedNetworks";
import {
  DEFAULT_PACE_MS, NOMINAL_TICK_DWELL_MS, ProtocolLabSim, TICK_PACES, TICK_PIPELINE,
  protocolLabCsvRows, type ProtocolLabState,
} from "./protocolLabSim";
import { RunSeeds } from "./runSeed";

const realWindow = (globalThis as { window?: unknown }).window;
beforeAll(() => {
  (globalThis as { window?: unknown }).window = {
    setInterval: (fn: () => void, ms: number) => setInterval(fn, ms),
    clearInterval: (id: number) => clearInterval(id),
  };
});
afterAll(() => {
  if (realWindow === undefined) delete (globalThis as { window?: unknown }).window;
  else (globalThis as { window?: unknown }).window = realWindow;
});

function driven(presetId: string, scenarioId: string | null = null, paceMs?: number) {
  let last!: ProtocolLabState;
  let n = 0;
  const sim = new ProtocolLabSim((s) => { last = s; }, {
    seeds: new RunSeeds(7), newKsid: () => `ksid-${++n}`, presetId, paceMs,
  });
  if (scenarioId) sim.loadPreset(presetId, scenarioId);
  return { sim, last: () => last };
}

const SCENARIOS: [string, string | null][] = [
  ...PRESETS.map((p) => [p.meta.id, null] as [string, string | null]),
  ["secoqc-vienna-2008", "secoqc-reroute-2008"],
  ["tokyo-2010", "tokyo-reroute-2010"],
  ["cambridge-2019", "cambridge-otp-reroute-2019"],
];

describe.each(SCENARIOS)("%s, scenario %s", (presetId, scenarioId) => {
  it("records nothing before the first tick", () => {
    expect(driven(presetId, scenarioId).last().last_tick).toBeNull();
  });

  it("runs exactly its mode's parts, in order, every tick", () => {
    const { sim, last } = driven(presetId, scenarioId);
    for (let i = 1; i <= 12; i++) {
      sim.step();
      const t = last().last_tick!;
      expect(t.tick).toBe(i);
      expect(t.t_s).toBe(last().sim_time_s);
      expect(t.steps.map((s) => s.id)).toEqual(TICK_PIPELINE[last().accounting].map((p) => p.id));
      for (const s of t.steps) expect(s.detail.length, s.id).toBeGreaterThan(0);
    }
  });

  it("says a key crossed only when the relay part says so, and along the route", () => {
    const { sim, last } = driven(presetId, scenarioId);
    for (let i = 0; i < 12; i++) {
      sim.step();
      const t = last().last_tick!;
      const relay = t.steps.find((s) => s.id === "relay");
      expect(t.relay !== null, `tick ${t.tick}`).toBe(relay?.outcome === "ok");
      if (t.relay) {
        expect(t.relay.linkIds).toHaveLength(t.relay.nodes.length - 1);
        expect(t.relay.nodes).toEqual(last().route!.nodes);
      }
    }
  });

  it("forgets the record on reset", () => {
    const { sim, last } = driven(presetId, scenarioId);
    sim.step();
    expect(last().last_tick).not.toBeNull();
    sim.reset();
    expect(last().last_tick).toBeNull();
  });
});

describe("what the parts report", () => {
  it("free play: a link with no way through reads as no route, and the delivery as refused", () => {
    const { sim, last } = driven("cambridge-2019");
    sim.setDemand("CAPE", "TREL", 1);
    sim.step();
    expect(last().last_tick!.steps.find((s) => s.id === "route")!.outcome).toBe("ok");
    sim.injectFailure({ kind: "node", id: "TREL" });
    sim.step();
    const steps = last().last_tick!.steps;
    expect(steps.find((s) => s.id === "route")!.outcome).toBe("fail");
    expect(steps.find((s) => s.id === "relay")!.outcome).toBe("fail");
    expect(last().last_tick!.relay).toBeNull();
    expect(last().route).toBeNull();
  });

  it("the cited SECOQC replay ends on a tick that says there is no route", () => {
    const { sim, last } = driven("secoqc-vienna-2008", "secoqc-reroute-2008");
    let steps = 0;
    while (last().route !== null && steps < 400) { sim.step(); steps += 1; }
    expect(last().route).toBeNull();
    const t = last().last_tick!;
    expect(t.steps.find((s) => s.id === "route")!.outcome).toBe("fail");
    expect(t.steps.find((s) => s.id === "deliver")!.outcome).toBe("fail");
    expect(t.relay).toBeNull();
  });

  it("Cambridge's replay relays only on the ticks it refills", () => {
    const { sim, last } = driven("cambridge-2019", "cambridge-otp-reroute-2019");
    let refills = 0;
    for (let i = 0; i < 80; i++) {
      const before = last().service!.refills;
      sim.step();
      const did = last().service!.refills > before;
      expect(last().last_tick!.relay !== null).toBe(did);
      if (did) refills += 1;
    }
    expect(refills).toBeGreaterThan(0);
  });
});

describe("the page's speed", () => {
  it("offers whole loop ticks, none of them another simulator's dwell", () => {
    expect(TICK_PACES.map((p) => p.ms)).toContain(NOMINAL_TICK_DWELL_MS);
    expect(TICK_PACES.map((p) => p.ms)).toContain(DEFAULT_PACE_MS);
    for (const p of TICK_PACES) {
      expect(p.ms % 100).toBe(0);
      expect([400, 500]).not.toContain(p.ms);
    }
  });

  it("is what the state and the CSV report, tick by tick", () => {
    const { sim, last } = driven(DEFAULT_PRESET_ID);
    expect(last().nominal_dwell_ms).toBe(NOMINAL_TICK_DWELL_MS);
    sim.step();
    sim.setPace(DEFAULT_PACE_MS);
    expect(last().nominal_dwell_ms).toBe(DEFAULT_PACE_MS);
    sim.step();
    const rows = protocolLabCsvRows(last());
    expect(rows.map((r) => r.nominal_dwell_ms)).toEqual([NOMINAL_TICK_DWELL_MS, DEFAULT_PACE_MS]);
  });

  it("refuses a value it does not offer, so no export can name a dwell the page never used", () => {
    const { sim, last } = driven(DEFAULT_PRESET_ID);
    sim.setPace(450);
    expect(last().nominal_dwell_ms).toBe(NOMINAL_TICK_DWELL_MS);
  });

  it("survives a reset and a change of network", () => {
    const { sim, last } = driven(DEFAULT_PRESET_ID);
    sim.setPace(DEFAULT_PACE_MS);
    sim.reset();
    expect(last().nominal_dwell_ms).toBe(DEFAULT_PACE_MS);
    sim.loadPreset("tokyo-2010", null);
    expect(last().nominal_dwell_ms).toBe(DEFAULT_PACE_MS);
  });

  it("changes nothing the engine computes", () => {
    const run = (paceMs: number) => {
      const { sim, last } = driven("secoqc-vienna-2008", "secoqc-reroute-2008", paceMs);
      for (let i = 0; i < 60; i++) sim.step();
      const s = last();
      return { delivered: s.delivered_bits, unmet: s.unmet_bits, route: s.route?.nodes, reroutes: s.reroutes,
               stores: s.links.map((l) => l.storedBits), steps: s.last_tick!.steps };
    };
    const [a, ...rest] = TICK_PACES.map((p) => run(p.ms));
    for (const b of rest) expect(b).toEqual(a);
  });
});
