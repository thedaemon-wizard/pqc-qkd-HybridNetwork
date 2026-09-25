/**
 * The cascade head and the cascade markers must run on ONE clock, and that
 * clock must stop whenever the simulation is not running.
 *
 * Two defects, each the mirror of the other:
 *
 *  1. The head ran on `FailureCascadeTimeline`'s own 500 ms wall-clock ticker
 *     with no reference to the run state, while the markers' `fired` flags were
 *     recomputed only in `PaperSim.snapshot()`. Measured on the deployed build,
 *     qkd failure injected then paused:
 *
 *         status: paused   t = 14.4s -> 28.4s -> 57.4s, no interaction
 *         status: paused   t = 257.4s, and the 180s and 240s markers still
 *                          dashed -- unfired. Only 0s is solid.
 *
 *  2. Gating the head's ticker on the run state fixed that direction and
 *     reversed it. `fired` was `Date.now() >= triggered_at` -- wall clock --
 *     so after an injection and a paused wait, a Step or a hop-slider change
 *     re-emitted the snapshot and flipped markers to fired while the head sat
 *     frozen at the time it had reached.
 *
 * Both came from having two clocks. PaperSim now keeps the only one
 * (`failure.elapsed_s`, accumulated in its tick while running), derives
 * `fired` from it, and the timeline draws its head from the same value.
 */
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import { readFileSync } from "node:fs";
import { join } from "node:path";

import { PaperSim, type PaperFlowState } from "../lib/sim/paperSim";

const HERE = new URL(".", import.meta.url).pathname;
const SRC = readFileSync(join(HERE, "FailureCascadeTimeline.tsx"), "utf8");
const PAGE = readFileSync(join(HERE, "../pages/PaperDataExchange.tsx"), "utf8");

describe("the timeline has no clock of its own", () => {
  it("takes the simulator's cascade clock as a prop", () => {
    expect(SRC).toMatch(/elapsedS: number;/);
    expect(SRC).toContain("activeLayer, startedAt, elapsedS, events, status,");
    expect(SRC).toMatch(/Math\.min\(max, elapsedS\)/);
  });

  it("runs no timer and keeps no elapsed state", () => {
    expect(SRC).not.toMatch(/setInterval|useState|useEffect/);
  });

  it("the page passes the simulator's clock and status", () => {
    expect(PAGE).toMatch(/<FailureCascadeTimeline\s+status=\{status\}/);
    expect(PAGE).toContain("elapsedS={state?.failure.elapsed_s ?? 0}");
  });
});

describe("the simulator's cascade clock", () => {
  // ensureLoop() calls window.setInterval; route it to the faked global timers.
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
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval", "Date", "performance"] });
  });
  afterEach(() => { vi.useRealTimers(); });

  function driven() {
    let last: PaperFlowState | null = null;
    const sim = new PaperSim((s) => { last = s; });
    const state = () => last as unknown as PaperFlowState;
    const fired = () => state().failure.cascade.filter((c) => c.fired).map((c) => c.t_offset_s);
    return { sim, state, fired };
  }

  it("does not advance while idle: a wait then a Step fires nothing new", () => {
    const { sim, state, fired } = driven();
    sim.injectFailure("qkd");
    vi.advanceTimersByTime(300_000);
    sim.step();
    expect(state().failure.elapsed_s).toBe(0);
    expect(fired()).toEqual([0]);
    sim.dispose();
  });

  it("advances while running, and fires exactly the stages it has reached", () => {
    const { sim, state, fired } = driven();
    sim.injectFailure("qkd");
    sim.start();
    vi.advanceTimersByTime(200_000);
    expect(state().failure.elapsed_s).toBeGreaterThan(199);
    expect(state().failure.elapsed_s).toBeLessThan(201);
    expect(fired()).toEqual([0, 180]);
    sim.dispose();
  });

  it("stops while paused, and a Step or a hop change does not move it", () => {
    const { sim, state, fired } = driven();
    sim.injectFailure("qkd");
    sim.start();
    vi.advanceTimersByTime(200_000);
    sim.pause();
    const frozen = state().failure.elapsed_s;
    vi.advanceTimersByTime(1_000_000);
    sim.step();
    sim.setHopCount(3);
    expect(state().failure.elapsed_s).toBe(frozen);
    expect(fired()).toEqual([0, 180]);

    // Resuming does not credit the paused gap.
    sim.resume();
    vi.advanceTimersByTime(50_000);
    expect(state().failure.elapsed_s).toBeLessThan(frozen + 51);
    expect(fired()).toEqual([0, 180, 240]);
    sim.dispose();
  });
});
