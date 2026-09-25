/**
 * /e2e must say what its run did: which mode a cycle ran in, what its rate
 * figure is paced by, which layers the figure lights, and how many packets it
 * sealed.
 *
 *  1. The mode buttons were disabled only while running, so a Pause or a Step
 *     part-way through a cycle let the mode change between step 2 and step 3:
 *     a QKD key drawn under C, then HKDF derived with info "mode-B" in a
 *     PQC-only mode.
 *  2. "Throughput" was one cycle's bytes over the cycle's wall-clock length,
 *     and the cycle is four fixed UI dwells -- a figure set by the animation.
 *  3. The architecture SVG lit the QKD path at step 2 in mode B, where no QKD
 *     key is drawn, and lit HKDF only in mode C, although every mode derives.
 *  4. Packets per cycle was a constant, although run parameters are meant to
 *     be settable on the page with config values as defaults.
 *  5. The page's own numbering is "step"; "phase" is the paper's word for a
 *     different scheme, and it survived in the exported JSON keys.
 */
import { describe, expect, it } from "vitest";

import { readFileSync } from "node:fs";
import { join } from "node:path";

import {
  DEFAULT_PACKETS_PER_CYCLE, E2ESim, PACKETS_PER_CYCLE_MAX, PACKETS_PER_CYCLE_MIN,
  STEPS_PER_CYCLE, type E2EState,
} from "../lib/sim/e2eSim";

const HERE = new URL(".", import.meta.url).pathname;
const PAGE = readFileSync(join(HERE, "QuantumSecureE2E.tsx"), "utf8");
const SIM = readFileSync(join(HERE, "../lib/sim/e2eSim.ts"), "utf8");

function driven() {
  let last: E2EState | null = null;
  const sim = new E2ESim((s) => { last = s; });
  sim.reset();
  return { sim, state: () => last as unknown as E2EState };
}

describe("a cycle runs in one mode", () => {
  it("setMode is refused part-way through a cycle", () => {
    const { sim, state } = driven();
    sim.setMode("C");
    sim.step(); sim.step();                   // steps 1 and 2 under C
    expect(state().current_step).toBeGreaterThan(0);
    expect(sim.setMode("B")).toBe(false);
    expect(state().mode).toBe("C");
    sim.step();                               // step 3 derives under C
    const s3 = state().history.find((h) => h.step === 3)!;
    expect(s3.detail.qkd_bytes).toBe(32);
    expect(s3.detail.pqc_bytes).toBe(32);
  });

  it("and accepted between cycles", () => {
    const { sim, state } = driven();
    for (let i = 0; i < STEPS_PER_CYCLE; i++) sim.step();
    expect(state().current_step).toBe(0);
    expect(sim.setMode("A")).toBe(true);
    expect(state().mode).toBe("A");
  });

  it("the page locks the buttons whenever a cycle is open, not only while running", () => {
    expect(PAGE).toContain('const modeLocked = status === "running" || step !== 0;');
    expect(PAGE).toContain("disabled={modeLocked}");
    expect(PAGE).toContain("Finish or Reset the cycle before changing mode");
  });
});

describe("the rate card says what paces it", () => {
  it("is not labelled a throughput", () => {
    expect(PAGE).not.toMatch(/label=\{`Throughput/);
    expect(PAGE).toContain("Animation-paced byte rate");
    expect(PAGE).toContain("not cipher or tunnel throughput");
  });

  it("shows the paced cycle length beside it", () => {
    expect(PAGE).toMatch(/state\.nominal_cycle_ms \/ 1000/);
  });

  it("the byte card counts what is on the wire and does not round it", () => {
    expect(PAGE).toContain("Bytes on the wire (ct + tag + nonce)");
    expect(PAGE).not.toContain("Bytes encrypted (×10³)");
  });
});

describe("the figure lights what the run did", () => {
  it("gates the QKD path on a QKD key actually being drawn", () => {
    expect(PAGE).toContain('const qkdLeg = mode !== "B" && failedLayer !== "qkd";');
    expect(PAGE).toContain("<KmsKeystore x={GEO.kms.lx}  active={qkdOn} />");
    expect(PAGE).toMatch(/label="QKD key_ID exchange {2}\(ETSI 014\)"\s+active=\{qkdOn\}/);
  });

  it("lights HKDF whenever either leg produced material, in every mode", () => {
    expect(PAGE).toContain("const hkdfOn = step === 3 && (qkdLeg || pqcLeg);");
    expect(PAGE).not.toContain('active={mode === "C" && phase === 3}');
  });

  it("does not key any highlight on a bare step number alone", () => {
    const svg = PAGE.slice(PAGE.indexOf("function ArchSvg("), PAGE.indexOf("function ArrowX("));
    const uses = svg.slice(svg.indexOf("return ("));
    expect(uses).not.toMatch(/(?:active|hot)=\{step === \d\}/);
  });
});

describe("packets per cycle is a page parameter", () => {
  it("defaults to the previous constant and is bounded", () => {
    const { state } = driven();
    expect(state().packets_per_cycle).toBe(DEFAULT_PACKETS_PER_CYCLE);
    expect(DEFAULT_PACKETS_PER_CYCLE).toBe(64);
    expect(PACKETS_PER_CYCLE_MIN).toBe(1);
    expect(PACKETS_PER_CYCLE_MAX).toBeGreaterThan(DEFAULT_PACKETS_PER_CYCLE);
  });

  it("refuses out-of-range values instead of clamping them", () => {
    const { sim, state } = driven();
    expect(sim.setPacketsPerCycle(0)).toBe(false);
    expect(sim.setPacketsPerCycle(PACKETS_PER_CYCLE_MAX + 1)).toBe(false);
    expect(sim.setPacketsPerCycle(2.5)).toBe(false);
    expect(state().packets_per_cycle).toBe(DEFAULT_PACKETS_PER_CYCLE);
  });

  it("is what step 4 seals, and survives a reset", () => {
    const { sim, state } = driven();
    expect(sim.setPacketsPerCycle(8)).toBe(true);
    for (let i = 0; i < STEPS_PER_CYCLE; i++) sim.step();
    expect(state().total_packets).toBe(8);
    sim.reset();
    expect(state().packets_per_cycle).toBe(8);
  });

  it("has a labelled input on the page", () => {
    expect(PAGE).toContain('aria-label="Packets per cycle"');
    expect(PAGE).toContain("setPacketsPerCycle(");
  });
});

describe("the run log says what was done and how much it shows", () => {
  it("records operator actions", () => {
    const { sim, state } = driven();
    sim.injectFailure("pqc");
    sim.step();
    const acts = state().operator_actions.map((a) => a.action);
    expect(acts).toEqual(["reset", "inject pqc", "step"]);
    expect(state().actions_total).toBe(3);
  });

  it("the log prints the failure, the paced cycle and 'last N of M'", () => {
    for (const s of ["# failed_layer:", "# nominal_cycle_ms:", "last ${s.history.length} of ${s.steps_total} shown",
                     "# operator actions (last"]) {
      expect(PAGE).toContain(s);
    }
  });
});

describe("'step', not 'phase', for this page's own numbering", () => {
  it("the run state uses step keys", () => {
    const { state } = driven();
    expect(Object.keys(state())).toContain("current_step");
    expect(Object.keys(state())).toContain("step_name");
    expect(Object.keys(state())).not.toContain("current_phase");
    expect(Object.keys(state())).not.toContain("phase_name");
  });

  it("neither the page nor the simulator reads a phase field", () => {
    for (const src of [PAGE, SIM]) {
      expect(src).not.toMatch(/\.current_phase\b|\.phase_name\b|\bh\.phase\b/);
    }
  });

  it("the step labels keep their numbering", () => {
    expect(PAGE).toContain('"1. Quantum Plane"');
    expect(PAGE).toContain('"4. Data Exchange (ChaCha20-Poly1305)"');
  });
});
