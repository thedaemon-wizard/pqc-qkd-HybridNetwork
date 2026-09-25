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
 * The two pages have DIFFERENT dwells -- 500 on /e2e, 400 on /paper-flow -- and
 * importing e2eSim's constant into the paper-flow page would export 500 for a
 * page that dwells 400: a fabricated number introduced by the change meant to
 * remove one. Hence "gives each page its OWN nominal" below.
 */
import { describe, expect, it } from "vitest";

import {
  E2ESim, NOMINAL_STEP_DWELL_MS as E2E_DWELL, e2eCsvRows,
  type E2EState, type StepRec,
} from "./e2eSim";
import {
  NOMINAL_PHASE_DWELL_MS as PAPER_DWELL, paperCsvRows, type PaperFlowState,
} from "./paperSim";
import { NOMINAL_TICK_DWELL_MS as LAB_DWELL } from "./protocolLabSim";
import { dwellDone, LOOP_TICK_MS } from "./pacing";
import { csvText } from "../exporters";

/**
 * One closed phase and one still open, in the shape each simulator records.
 *
 * The closed /e2e phase carries the dwell actually measured on the deployed
 * demo with the tab hidden -- 999 ms, against the 500 ms nominal now in force (450 ms
 * when it was measured) -- so the ratio
 * asserted below is computed from an exported row rather than from two
 * literals defined next to it.
 */
const T0 = 1_700_000_000;

/**
 * Measured over nominal dwell above which a recording was throttled. A
 * foreground run reads about 1.0 and the demo's hidden-tab recordings about
 * 2.0 (999 ms against 500 ms; 3.995 s against a 2.0 s cycle), so the midpoint
 * separates the two with room either side.
 */
const THROTTLED_RATIO = 1.5;
const E2E_HISTORY: StepRec[] = [
  { step: 1, name: "Quantum Plane", started_at: T0, completed_at: T0 + 0.999,
    detail: { alice_pool: 3 } },
  { step: 2, name: "QKD Key IDs (ETSI 014)", started_at: T0 + 1,
    completed_at: null, detail: {} },
];
const PAPER_HISTORY: PaperFlowState["history"] = [
  { phase: 1, name: "Quantum Plane", started_at: T0, completed_at: T0 + 0.35,
    packets: 0, bytes: 0, detail: {} },
  { phase: 2, name: "Arnika QKD key_ID exchange", started_at: T0 + 1,
    completed_at: null, packets: 2, bytes: 78, detail: {} },
];

/** The header row of /e2e's CSV export for one healthy cycle, column for column. */
const E2E_CSV_HEADER =
  "step,name,started_at,completed_at,ui_dwell_ms,nominal_dwell_ms,"
  + "alice_pool,key_id,qkd_key_len,psk_prefix,qkd_bytes,pqc_bytes,"
  + "packets,bytes,rate_mbps";

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

  it("keeps all three simulators' dwells distinct, /protocol-lab included", () => {
    // The third simulator publishes `nominal_dwell_ms` too
    // (protocolLabSim.test.ts checks its CSV); a shared value would make a
    // wrong import look right here as well.
    expect(new Set([E2E_DWELL, PAPER_DWELL, LAB_DWELL]).size).toBe(3);
    expect(LAB_DWELL).toBe(300);
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
    // Whole numbers of the 100 ms loop tick: 450 and 350 were advanced on the
    // fifth and fourth tick, so every foreground run dwelt 500 and 400 while
    // the export said 450 and 350 -- and looked throttled.
    expect(E2E_DWELL).toBe(500);
    expect(PAPER_DWELL).toBe(400);
    for (const d of [E2E_DWELL, PAPER_DWELL, LAB_DWELL]) expect(d % LOOP_TICK_MS).toBe(0);
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
    // constant into the paper-flow page would export 500 for a page that
    // dwells 400.
    expect(e2eCsvRows(E2E_HISTORY)[0].nominal_dwell_ms).toBe(E2E_DWELL);
    expect(paperCsvRows(PAPER_HISTORY)[0].nominal_dwell_ms).toBe(PAPER_DWELL);
  });

  it("rounds ui_dwell_ms to whole ms and leaves an open phase blank", () => {
    expect(e2eCsvRows(E2E_HISTORY)[0].ui_dwell_ms).toBe(999);
    expect(e2eCsvRows(E2E_HISTORY)[1].ui_dwell_ms).toBe("");
    expect(paperCsvRows(PAPER_HISTORY)[0].ui_dwell_ms).toBe(350);
    expect(paperCsvRows(PAPER_HISTORY)[1].ui_dwell_ms).toBe("");
  });

  it("ships exactly this /e2e header on a healthy cycle", () => {
    // Read from the text downloadCSV saves, for rows from a real cycle, so a
    // renamed, dropped or reordered column fails here rather than in someone's
    // spreadsheet. The fixed columns come first; the rest are the step detail
    // keys, in the order the steps first record them (alice_pool at step 1,
    // key_id and qkd_key_len at step 2, the PSK prefix and the two HKDF input
    // lengths at step 3, the traffic totals at step 4). A failed layer adds
    // `failed`, `fatal` or `note`; a healthy hybrid-mode cycle adds none.
    const header = csvText(e2eCsvRows(e2eCycle().history)).split("\n")[0];
    expect(header).toBe(E2E_CSV_HEADER);
    expect(header.startsWith("step,")).toBe(true);
  });

  it("lets a reader detect the throttling from one exported row", () => {
    // Both terms are read out of the row, so this stops holding the moment
    // either column is dropped or renamed -- which is the point of the test.
    // A foreground row now reads ~1.0 (the nominal is the real foreground
    // dwell); the hidden-tab row measured on the demo reads ~2. Anything past
    // 1.5 is a throttled recording, not a slow simulator.
    const [hidden] = e2eCsvRows(E2E_HISTORY);
    expect((hidden.ui_dwell_ms as number) / (hidden.nominal_dwell_ms as number))
      .toBeGreaterThan(THROTTLED_RATIO);
  });
});

describe("rate_bps has the same wall-clock dependence", () => {
  /**
   * Found while fact-checking /e2e's exported numbers. The arithmetic is
   * right -- bytes x 8 / seconds, correct units -- but the denominator is
   * measured, so a hidden tab understates throughput.
   *
   * Measured on the demo: 4470 bytes reported at 8952 bps, implying 3.995 s
   * for a cycle whose real foreground length is 4 x 500 ms = 2.0 s (it was
   * documented as 4 x 450 = 1.8 s, which the 100 ms loop never achieved). The
   * dwell column had already been fixed this way and rate_bps had been left
   * behind.
   *
   * The nominal below is read off a real run rather than recomputed here, so
   * these fail if the simulator stops publishing the term a reader needs.
   */
  it("publishes both terms of the comparison in the run state", () => {
    const s = e2eCycle();
    expect(s.nominal_cycle_ms).toBe(4 * E2E_DWELL);
    expect(s.nominal_cycle_ms).toBe(2000);
    expect(s.rate_bps).toBeGreaterThan(0);
    expect(s.total_bytes_encrypted).toBeGreaterThan(0);
  });

  it("detects the throttled recording actually observed", () => {
    const impliedElapsedMs = ((4470 * 8) / 8952.08531538921) * 1000;
    expect(impliedElapsedMs / e2eCycle().nominal_cycle_ms).toBeGreaterThan(THROTTLED_RATIO);
  });

  it("does not flag a foreground run", () => {
    const impliedElapsedMs = ((4470 * 8) / 17880) * 1000;   // ~2.0 s
    expect(impliedElapsedMs / e2eCycle().nominal_cycle_ms).toBeLessThan(1.2);
  });
});

describe("the nominal is the dwell a foreground run actually gets", () => {
  it("advances on the tick that reaches the nominal, whatever the jitter", () => {
    // Ticks land a few ms either side of each 100 ms mark. Half a tick of
    // tolerance means the advance neither slips to the next tick when a tick
    // lands at 499 ms nor fires a tick early at 401 ms.
    for (const nominal of [E2E_DWELL, PAPER_DWELL, LAB_DWELL]) {
      expect(dwellDone(nominal - 3, nominal)).toBe(true);
      expect(dwellDone(nominal - LOOP_TICK_MS + 3, nominal)).toBe(false);
    }
  });
});
