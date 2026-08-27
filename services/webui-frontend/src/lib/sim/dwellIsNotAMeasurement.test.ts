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

import {
  E2ESim, NOMINAL_PHASE_DWELL_MS as E2E_DWELL, e2eCsvRows,
  type E2EState, type PhaseRec,
} from "./e2eSim";
import {
  NOMINAL_PHASE_DWELL_MS as PAPER_DWELL, paperCsvRows, type PaperFlowState,
} from "./paperSim";

/**
 * One closed phase and one still open, in the shape each simulator records.
 *
 * The closed /e2e phase carries the dwell actually measured on the deployed
 * demo with the tab hidden -- 999 ms against a 450 ms nominal -- so the ratio
 * asserted below is computed from an exported row rather than from two
 * literals defined next to it.
 */
const T0 = 1_700_000_000;
const E2E_HISTORY: PhaseRec[] = [
  { phase: 1, name: "Quantum Plane", started_at: T0, completed_at: T0 + 0.999,
    detail: { alice_pool: 3 } },
  { phase: 2, name: "QKD Key IDs (ETSI 014)", started_at: T0 + 1,
    completed_at: null, detail: {} },
];
const PAPER_HISTORY: PaperFlowState["history"] = [
  { phase: 1, name: "Quantum Plane", started_at: T0, completed_at: T0 + 0.35,
    packets: 0, bytes: 0, detail: {} },
  { phase: 2, name: "Arnika QKD key_ID exchange", started_at: T0 + 1,
    completed_at: null, packets: 2, bytes: 78, detail: {} },
];

/** One full /e2e cycle, driven through the real simulator. */
function e2eCycle(): E2EState {
  let last: E2EState | null = null;
  const sim = new E2ESim((s) => { last = s; });
  for (let i = 0; i < 4; i++) sim.step();
  return last as unknown as E2EState;
}

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

describe("the columns the export actually ships", () => {
  const rows = [...e2eCsvRows(E2E_HISTORY), ...paperCsvRows(PAPER_HISTORY)];

  it("never ships a column named duration_ms again", () => {
    // The original defect. Nothing in this file could observe it before:
    // every assertion here ran on the two dwell constants alone, so the
    // pre-fix column set passed this suite untouched.
    for (const row of rows) expect(Object.keys(row)).not.toContain("duration_ms");
  });

  it("publishes the nominal beside the measured dwell, on both pages", () => {
    for (const row of rows) {
      expect(Object.keys(row)).toContain("ui_dwell_ms");
      expect(Object.keys(row)).toContain("nominal_dwell_ms");
    }
  });

  it("gives each page its OWN nominal, not the other page's", () => {
    // The near-miss described at the top of this file: importing e2eSim's
    // constant into the paper-flow page would have exported 450 for a page
    // that dwells 350.
    expect(e2eCsvRows(E2E_HISTORY)[0].nominal_dwell_ms).toBe(E2E_DWELL);
    expect(paperCsvRows(PAPER_HISTORY)[0].nominal_dwell_ms).toBe(PAPER_DWELL);
  });

  it("rounds ui_dwell_ms to whole ms and leaves an open phase blank", () => {
    expect(e2eCsvRows(E2E_HISTORY)[0].ui_dwell_ms).toBe(999);
    expect(e2eCsvRows(E2E_HISTORY)[1].ui_dwell_ms).toBe("");
    expect(paperCsvRows(PAPER_HISTORY)[0].ui_dwell_ms).toBe(350);
    expect(paperCsvRows(PAPER_HISTORY)[1].ui_dwell_ms).toBe("");
  });

  it("lets a reader detect the throttling from one exported row", () => {
    // Both terms are read out of the row, so this stops holding the moment
    // either column is dropped or renamed -- which is the point of the test.
    const [hidden] = e2eCsvRows(E2E_HISTORY);
    expect((hidden.ui_dwell_ms as number) / (hidden.nominal_dwell_ms as number))
      .toBeGreaterThan(2);
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
   *
   * The nominal below is read off a real run rather than recomputed here, so
   * these fail if the simulator stops publishing the term a reader needs.
   */
  it("publishes both terms of the comparison in the run state", () => {
    const s = e2eCycle();
    expect(s.nominal_cycle_ms).toBe(4 * E2E_DWELL);
    expect(s.nominal_cycle_ms).toBe(1800);
    expect(s.rate_bps).toBeGreaterThan(0);
    expect(s.total_bytes_encrypted).toBeGreaterThan(0);
  });

  it("detects the throttled recording actually observed", () => {
    const impliedElapsedMs = ((4470 * 8) / 8952.08531538921) * 1000;
    expect(impliedElapsedMs / e2eCycle().nominal_cycle_ms).toBeGreaterThan(2);
  });

  it("does not flag a foreground run", () => {
    const impliedElapsedMs = ((4470 * 8) / 19866) * 1000;   // ~1.8 s
    expect(impliedElapsedMs / e2eCycle().nominal_cycle_ms).toBeLessThan(1.2);
  });
});
