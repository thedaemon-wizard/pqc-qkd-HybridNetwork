/**
 * The phase-duration column is a UI constant, and the export has to say so.
 *
 * `/e2e` exported a CSV column named `duration_ms`, computed as the wall-clock
 * gap between a phase starting and finishing. In a research artefact that name
 * reads as a protocol measurement. It is not one. It is the animation dwell --
 * the source comment for the constant says "so the animation is watchable" --
 * and the browser distorts even that: Chrome clamps `setInterval` to roughly
 * 1 Hz in a hidden tab.
 *
 * Measured on the deployed demo: `visibilityState: "hidden"`, a requested
 * 100 ms interval firing every 935 ms, and phases logging 999 ms against a
 * 450 ms nominal. Someone plotting that column would be plotting Chrome's
 * throttling policy.
 *
 * The column is now `ui_dwell_ms`, published beside `nominal_dwell_ms` so the
 * distortion is visible in the data rather than hidden by it.
 *
 * The two pages have DIFFERENT dwells -- 450 on /e2e, 350 on /paper-flow -- and
 * the first attempt at this fix imported e2eSim's constant into the paper-flow
 * page, which would have exported 450 for a page that dwells 350: a fabricated
 * number introduced by the change meant to remove one. Hence the last test.
 */
import { describe, expect, it } from "vitest";

import { NOMINAL_PHASE_DWELL_MS as E2E_DWELL } from "./e2eSim";
import { NOMINAL_PHASE_DWELL_MS as PAPER_DWELL } from "./paperSim";

describe("the nominal dwell is published", () => {
  it("is a positive number on both simulators", () => {
    for (const d of [E2E_DWELL, PAPER_DWELL]) {
      expect(Number.isFinite(d)).toBe(true);
      expect(d).toBeGreaterThan(0);
    }
  });

  it("keeps the two pages' dwells distinct", () => {
    // If these ever became equal, a single shared import would look correct
    // and the guard below would stop meaning anything. They are different
    // because the two animations are paced differently, and that is the whole
    // reason each page must export its own.
    expect(E2E_DWELL).not.toBe(PAPER_DWELL);
  });

  it("matches the dwell each simulator actually paces itself with", () => {
    // Pins the values so a change to the pacing cannot silently leave the
    // exported nominal describing the old animation.
    expect(E2E_DWELL).toBe(450);
    expect(PAPER_DWELL).toBe(350);
  });
});

describe("what a throttled recording looks like", () => {
  /**
   * Not a test of our code -- a test of the reasoning the export encodes. If
   * measured and nominal diverge by this much, the run was throttled and the
   * timing column carries no information about the simulation.
   */
  const throttledRatio = (measuredMs: number, nominalMs: number) => measuredMs / nominalMs;

  it("flags the ratio actually observed on the deployed demo", () => {
    // 999 ms measured against the 450 ms nominal, tab hidden.
    expect(throttledRatio(999, E2E_DWELL)).toBeGreaterThan(2);
  });

  it("does not flag a foreground run", () => {
    // A visible tab lands within a tick of the nominal.
    expect(throttledRatio(470, E2E_DWELL)).toBeLessThan(1.2);
  });
});

describe("rate_bps has the same wall-clock dependence", () => {
  /**
   * Found while fact-checking /e2e's exported numbers. The arithmetic is
   * right -- bytes x 8 / seconds, correct units -- but the denominator is
   * measured, so a hidden tab understates throughput.
   *
   * Measured on the demo: 4470 bytes reported at 8952 bps, implying 3.995 s
   * for a cycle whose nominal length is 4 x 450 ms = 1.8 s. The dwell column
   * had already been fixed this way and rate_bps had been left behind.
   */
  const NOMINAL_CYCLE_MS = 4 * E2E_DWELL;

  it("publishes a nominal cycle to compare the rate against", () => {
    expect(NOMINAL_CYCLE_MS).toBe(1800);
  });

  it("detects the throttled recording actually observed", () => {
    const impliedElapsedS = (4470 * 8) / 8952.08531538921;
    const ratio = (impliedElapsedS * 1000) / NOMINAL_CYCLE_MS;
    expect(ratio).toBeGreaterThan(2);   // ~2.2x, the throttle
  });

  it("does not flag a foreground run", () => {
    const foreground = (4470 * 8) / 19866;   // ~1.8 s
    expect((foreground * 1000) / NOMINAL_CYCLE_MS).toBeLessThan(1.2);
  });
});
