/**
 * The three cited scenarios, replayed and compared with what their sources
 * report.
 *
 * SECOQC is a consistency check rather than independent evidence: the routing
 * rule (fewest hops, then widest bottleneck) was chosen because it reproduces
 * the published order. The replay's TIMES are independent of that choice --
 * they follow from the cited stores, threshold and demand alone -- and so is
 * Cambridge's switch back after the outage.
 */
import { afterAll, beforeAll, describe, expect, it } from "vitest";

import { ProtocolLabSim, type ProtocolLabState } from "../protocolLabSim";
import { RunSeeds } from "../runSeed";
import { MIB_BITS, quantityValue, scenarioById } from "./publishedNetworks";

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

function run(presetId: string, scenarioId: string | null) {
  let last!: ProtocolLabState;
  let n = 0;
  const sim = new ProtocolLabSim((s) => { last = s; }, {
    seeds: new RunSeeds(7), newKsid: () => `ksid-${++n}`, presetId,
  });
  sim.loadPreset(presetId, scenarioId);
  return { sim, state: () => last };
}

describe("SECOQC re-routing (Peev et al. 2009, section 5.1.2)", () => {
  const { sim, state } = run("secoqc-vienna-2008", "secoqc-reroute-2008");
  // Step until the run halts on "no route", with a bound so a regression
  // cannot hang the suite.
  for (let i = 0; i < 400 && state().route !== null; i++) sim.step();
  const s = state();
  const moves = s.reroutes.map((r) => ({ t: r.t_s, to: r.to?.join("-") ?? null, why: r.reason }));

  it("uses the three published routes in the published order, then none", () => {
    expect(moves.map((m) => m.to)).toEqual([
      "FOR-ERD-BRT", "FOR-ERD-SIE-BRT", "FOR-ERD-GUD-BRT", null,
    ]);
  });

  it("leaves route 1 after about an hour, as the source says", () => {
    // 3.5 MiB above the 2 MiB threshold at 8192 bit/s is 3584 s; with
    // one-minute ticks the last full tick ends at 3540 s.
    const t = moves[1].t;
    expect(t).toBeGreaterThanOrEqual(3540);
    expect(t).toBeLessThanOrEqual(3600);
  });

  it("runs route 3 for about half an hour (published: minute 144 to 175)", () => {
    const r3 = moves[3].t - moves[2].t;
    expect(Math.abs(r3 - 31 * 60)).toBeLessThanOrEqual(60);
  });

  it("replays route 2 SHORTER than published, because two stores' generation is unquantified", () => {
    // Published: about 84 minutes. The replay generates nothing on ERD-SIE and
    // SIE-BRT (the source gives no rate), so its lifetime is a lower bound.
    const r2 = (moves[2].t - moves[1].t) / 60;
    expect(r2).toBeLessThan(84);
    expect(Math.abs(r2 - 68.3)).toBeLessThanOrEqual(1);
    expect(s.limits.join(" ")).toMatch(/lower bound/);
  });

  it("FOR-ERD never reaches its threshold, as the source says ('used all the time')", () => {
    const forErd = s.links.find((l) => l.id === "ERD-FOR")!;
    expect(forErd.storedBits! - forErd.thresholdBits!).toBeGreaterThan(0);
    // About 5.3 MiB remain above the threshold.
    expect((forErd.storedBits! - forErd.thresholdBits!) / MIB_BITS).toBeGreaterThan(3);
  });

  it("SIE-BRT, not ERD-SIE, is the store that ends route 2", () => {
    const sieBrt = s.links.find((l) => l.id === "SIE-BRT")!;
    const erdSie = s.links.find((l) => l.id === "SIE-ERD")!;
    const need = quantityValue(scenarioById("secoqc-reroute-2008").demand.rate) * s.tick_s;
    expect(sieBrt.storedBits! - sieBrt.thresholdBits!).toBeLessThan(need);
    expect(erdSie.storedBits! - erdSie.thresholdBits!).toBeGreaterThan(need);
  });

  it("halts when no route is left, and says why", () => {
    expect(s.route).toBeNull();
    expect(s.route_none).toBeTruthy();
  });

  it("carries the source's route list for comparison", () => {
    expect(s.published?.routes.length).toBe(3);
  });
});

describe("Tokyo switch-over (Sasaki et al. 2011, section 4)", () => {
  const { sim, state } = run("tokyo-2010", "tokyo-reroute-2010");
  sim.step();
  const before = state().route!;
  sim.injectFailure({ kind: "link", id: "K1-K2", reason: "qber-alarm" });
  sim.step();
  const after = state().route!;
  sim.clearFailure({ kind: "link", id: "K1-K2" });
  sim.step();
  const back = state().route!;

  it("starts on the primary route via Koganei-2", () => {
    expect(before.nodes).toEqual(["K1", "K2", "O2"]);
    expect(before.relays).toBe(1);
  });

  it("moves to the route via Otemachi-1 on the QBER alarm", () => {
    expect(after.nodes).toEqual(["K1", "O1", "O2"]);
    expect(after.relays).toBe(1);
    expect(state().reroutes.some((r) => r.reason === "qber-alarm")).toBe(true);
  });

  it("returns to the primary route when the alarm clears", () => {
    expect(back.nodes).toEqual(["K1", "K2", "O2"]);
  });

  it("does not evaluate rate sufficiency, and says so", () => {
    expect(state().accounting).toBe("route-only");
    expect(state().limits.join(" ")).toMatch(/rate sufficiency is not evaluated/);
  });
});

describe("Cambridge refill and outage (Dynes et al. 2019, Fig. 3)", () => {
  const { sim, state } = run("cambridge-2019", "cambridge-otp-reroute-2019");
  const routesUsed = new Set<string>();
  const stepN = (n: number) => {
    for (let i = 0; i < n; i++) {
      const refillsBefore = state().service!.refills;
      sim.step();
      if (state().service!.refills > refillsBefore) routesUsed.add(state().route!.nodes.join("-"));
    }
  };
  // 200 keys at 0.5 keys/s is 400 s, 40 ten-second ticks: step past two refills.
  stepN(90);
  const phase1 = new Set(routesUsed); routesUsed.clear();
  sim.injectFailure({ kind: "link", id: "CAPE-TREL", reason: "outage" });
  stepN(90);
  const phase2 = new Set(routesUsed); routesUsed.clear();
  sim.clearFailure({ kind: "link", id: "CAPE-TREL" });
  stepN(90);
  const phase3 = new Set(routesUsed);

  it("refills over CAPE-TREL", () => {
    expect([...phase1]).toEqual(["TREL-CAPE"]);
  });

  it("moves the refills round the ring during the outage", () => {
    expect([...phase2]).toEqual(["TREL-ENGI-CAPE"]);
  });

  it("switches back to CAPE-TREL on restore", () => {
    expect([...phase3]).toEqual(["TREL-CAPE"]);
  });

  it("never fails a key request, as the source reports", () => {
    expect(state().requests_failed).toBe(0);
    expect(state().service!.failedRefills).toBe(0);
    expect(state().requests_ok).toBeGreaterThan(0);
  });
});
