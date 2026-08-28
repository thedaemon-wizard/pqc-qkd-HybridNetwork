/**
 * The /paper-flow KPI cards must not state arithmetic the simulator does not do.
 *
 * Read live on the public demo 2026-08-28, mid-run:
 *
 *   Sim cycles done                      3
 *   Sim bytes (paper budget x cycles)    10624
 *
 * 3 x 5248 = 15744, not 10624. Both numbers were correct; the LABEL was not.
 *
 *   * `cycles_total` counts cycles STARTED -- beginCycle() increments it
 *     before any phase has run. The card said "done".
 *   * `bytes_total` accrues per PHASE as each completes, so mid-cycle it is
 *     not a multiple of the 5248 per-handshake budget. 10624 is two completed
 *     cycles (2 x 5248 = 10496) plus two ~64 B ChaCha20-Poly1305 records.
 *
 * A reader who checks the stated multiplication finds it fails and cannot tell
 * which number to distrust. Nothing could catch it: no test asserted on a card
 * label, and both underlying counters were right.
 *
 * These drive the simulator through step(), which advances exactly one phase
 * without the timer, so the accounting is checked deterministically rather
 * than by sleeping.
 */
import { describe, expect, it } from "vitest";

import { PaperSim } from "./paperSim";
import type { PaperFlowState } from "./paperSim";

/** Drive the sim without the wall clock. Returns the latest emitted state. */
function driver() {
  let last: PaperFlowState | null = null;
  const sim = new PaperSim((s) => { last = s; });
  return {
    sim,
    get state(): PaperFlowState { return last ?? sim.snapshot(); },
    /** step() n times; each call advances one phase (or opens the first cycle). */
    steps(n: number) { for (let i = 0; i < n; i++) sim.step(); return this.state; },
  };
}

const budget = (s: PaperFlowState) => s.paper_budgets.total_handshake_bytes;

describe("the paper budget the cards quote", () => {
  it("is the sum of the phase table, not a constant typed twice", () => {
    const s = driver().state;
    const bytes = s.paper_budgets.phases.reduce((a, p) => a + p.bytes, 0);
    const pkts = s.paper_budgets.phases.reduce((a, p) => a + p.packets, 0);
    expect(bytes).toBe(s.paper_budgets.total_handshake_bytes);
    expect(pkts).toBe(s.paper_budgets.total_handshake_packets);
    // arXiv:2604.05599 Table 1.
    expect(bytes).toBe(5248);
    expect(pkts).toBe(9);
  });
});

describe("cycles_total counts starts, not completions", () => {
  it("reaches 1 before any phase has produced a byte", () => {
    const d = driver();
    const s = d.steps(1);
    expect(s.cycles_total).toBe(1);
    expect(s.cycles_succeeded).toBe(0);
    expect(s.bytes_total).toBe(0);
  });

  it("cycles_succeeded never exceeds cycles_total", () => {
    const d = driver();
    for (let i = 0; i < 40; i++) {
      const s = d.steps(1);
      expect(s.cycles_succeeded).toBeLessThanOrEqual(s.cycles_total);
    }
  });
});

describe("bytes_total is a per-phase accrual", () => {
  it("is NOT paper-budget times cycles_total -- the relation the label claimed", () => {
    // The whole point of this file. If this never diverges, the old label was
    // right and the diagnosis above is wrong.
    const d = driver();
    let sawMismatch = false;
    for (let i = 0; i < 40; i++) {
      const s = d.steps(1);
      if (s.cycles_total > 0 && s.bytes_total !== budget(s) * s.cycles_total) {
        sawMismatch = true;
        break;
      }
    }
    expect(sawMismatch,
      "bytes_total tracked 5248 x cycles_total at every step, which would mean "
      + "the old card label was correct").toBe(true);
  });

  it("never exceeds what the started cycles could have produced", () => {
    // The honest bound: phase bytes plus the sealed data records.
    const d = driver();
    for (let i = 0; i < 40; i++) {
      const s = d.steps(1);
      expect(s.bytes_total).toBeLessThanOrEqual(
        (budget(s) + 256) * Math.max(s.cycles_total, 1));
    }
  });

  it("only ever increases", () => {
    const d = driver();
    let prev = 0;
    for (let i = 0; i < 40; i++) {
      const b = d.steps(1).bytes_total;
      expect(b).toBeGreaterThanOrEqual(prev);
      prev = b;
    }
  });

  it("resets to zero with the cycle counters", () => {
    const d = driver();
    d.steps(12);
    expect(d.state.bytes_total).toBeGreaterThan(0);
    d.sim.reset();
    const s = d.state;
    expect(s.bytes_total).toBe(0);
    expect(s.cycles_total).toBe(0);
    expect(s.cycles_succeeded).toBe(0);
    expect(s.status).toBe("idle");
  });
});

describe("the hop slider does not fabricate traffic", () => {
  it("changing hop count leaves the byte total unchanged", () => {
    // The page caption says so explicitly: "Moving the trusted-node slider
    // from 1 to 8 changes the total by zero, because no per-hop traffic is
    // being counted." If that stops holding, the caption becomes false.
    const totals = [1, 4, 8].map((hops) => {
      const d = driver();
      d.sim.setHopCount(hops);
      d.steps(12);
      return d.state.bytes_total;
    });
    expect(new Set(totals).size,
      `hop count changed the byte total: ${totals.join(", ")}`).toBe(1);
  });

  it("the hop count itself is clamped to the slider's range", () => {
    const d = driver();
    d.sim.setHopCount(99);
    expect(d.state.hop_count).toBe(8);
    d.sim.setHopCount(-5);
    expect(d.state.hop_count).toBe(1);
  });
});

// step()'s refuse-while-running behaviour is deliberately NOT tested here:
// start() calls window.setInterval (paperSim.ts:238) and this file runs in the
// node environment. Pulling in jsdom to assert one guard would make the whole
// accounting suite depend on a DOM it otherwise never touches.


describe("the page states the budget once, not twice", () => {
  it("the subtitle derives the totals rather than hardcoding them", async () => {
    const { readFileSync } = await import("node:fs");
    const { join } = await import("node:path");
    const page = readFileSync(
      join(new URL(".", import.meta.url).pathname, "../../pages/PaperDataExchange.tsx"),
      "utf8");
    const subtitle = page.slice(page.indexOf("subtitle="), page.indexOf("subtitle=") + 1400);
    expect(subtitle).toContain("total_handshake_packets");
    expect(subtitle).toContain("total_handshake_bytes");
    // Strip JSX comments before checking for the literal. The fix's own
    // explanatory comment QUOTES the old wording in order to retract it, and a
    // bare match flagged that as the offence -- the fourth time this
    // self-reference trap has appeared in this suite.
    const rendered = subtitle.replace(/\{\/\*[\s\S]*?\*\/\}/g, "");
    expect(rendered, "the subtitle hardcodes the totals again, so a phase-table "
      + "edit would move the cards and leave the sentence asserting the old "
      + "figure -- and the sentence is the one a reader quotes")
      .not.toMatch(/9 packets \/ 5248 bytes/);
  });

  it("the phase table is still the single source of both", () => {
    const s = driver().state;
    const bytes = s.paper_budgets.phases.reduce((a, p) => a + p.bytes, 0);
    const pkts = s.paper_budgets.phases.reduce((a, p) => a + p.packets, 0);
    expect(s.paper_budgets.total_handshake_bytes).toBe(bytes);
    expect(s.paper_budgets.total_handshake_packets).toBe(pkts);
  });
});
