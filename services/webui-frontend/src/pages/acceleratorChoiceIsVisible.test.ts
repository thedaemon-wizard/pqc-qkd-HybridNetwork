/**
 * The accelerator benchmark is a result, not a secret.
 *
 * `/bb84` picks its compute tier by measuring: it starts a CPU Web Worker,
 * then benchmarks a WebGPU compute shader and a WebGL2 GPGPU pass, adopting a
 * GPU tier only if it beats the worker by 15 %. That is good design -- no
 * unconditional fallback, the choice is data.
 *
 * The result then went to `console.info` and nowhere else. The page showed
 * `⚡ Worker (CPU) · 58.8M pulses/s` and a reader concluded the WebGPU path was
 * not implemented. Measured on the deployed demo 2026-08-28, from the browser
 * console, five consecutive rounds:
 *
 *     [bb84] WebGPU 33M/s <= Worker 42M/s -- keeping Worker
 *     [bb84] WebGPU 38M/s <= Worker 47M/s -- keeping Worker
 *     [bb84] WebGPU 40M/s <= Worker 42M/s -- keeping Worker
 *     [bb84] WebGPU 39M/s <= Worker 57M/s -- keeping Worker
 *     [bb84] WebGPU 50M/s <= Worker 61M/s -- keeping Worker
 *
 * `navigator.gpu` was present throughout. The shader compiled, ran, and lost.
 * "We tried the GPU and the CPU was faster on this hardware" and "there is no
 * GPU path" are different claims, and the page was making the wrong one by
 * omission -- the same defect `/benchmarks` had with `skr_provenance`, which
 * provenanceReachesTheScreen.test.ts was written for.
 */
import { describe, expect, it } from "vitest";

import { readFileSync } from "node:fs";
import { join } from "node:path";

import { engineChoiceSummary } from "../lib/sim/engineChoice";
import type { TierTrial } from "../lib/sim/bb84Sim";

const stripComments = (s: string) =>
  s.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");

const HERE = new URL(".", import.meta.url).pathname;
const BB84 = readFileSync(join(HERE, "BB84.tsx"), "utf8");
const SIM = readFileSync(join(HERE, "../lib/sim/bb84Sim.ts"), "utf8");

// The observed demo numbers, so the test is anchored to a real measurement.
const OBSERVED: TierTrial[] = [
  { tier: "WebGPU (compute shader)", pulsesPerSec: 50e6, adopted: false },
];

describe("the tier benchmark reaches the page", () => {
  it("the summary names the tier, its rate and that it was not adopted", () => {
    const s = engineChoiceSummary(OBSERVED, 61e6);
    expect(s).toContain("WebGPU (compute shader)");
    expect(s).toContain("50.0M/s");
    expect(s).toContain("61.0M/s");        // what it lost to
    expect(s).toMatch(/not adopted/);
  });

  it("an adopted tier says so instead", () => {
    const s = engineChoiceSummary(
      [{ tier: "WebGPU (compute shader)", pulsesPerSec: 90e6, adopted: true }], 61e6);
    expect(s).toContain("(adopted)");
    expect(s).not.toMatch(/not adopted/);
  });

  it("a tier that could not initialise is distinguishable from a slow one", () => {
    // The whole point: "absent" and "measured and slower" must not collapse.
    const s = engineChoiceSummary(
      [{ tier: "WebGPU (compute shader)", pulsesPerSec: null, adopted: false,
         error: "not available in this browser" }], 61e6);
    expect(s).toContain("not available in this browser");
    expect(s).not.toMatch(/0\.0M\/s/);
  });

  it("says nothing has been measured yet rather than implying zero", () => {
    expect(engineChoiceSummary([], null)).toMatch(/has not run yet/);
  });
});

describe("the record is produced and rendered, not just typed", () => {
  it("every tier outcome is recorded, including the unavailable branch", () => {
    // Four sites per tier -- adopted / slower / unavailable / threw -- across
    // WebGPU, WebGL2 and WASM. If any is dropped the panel silently omits a
    // tier, which is the omission this whole file exists to prevent.
    const code = stripComments(SIM);
    const records = code.match(/this\.record\(\{/g) ?? [];
    expect(records.length).toBe(12);
    expect(code).toContain('error: "not available in this browser"');
    expect(code).toContain('error: "WebAssembly not available in this browser"');
  });

  it("all three accelerator tiers are named and benchmarked", () => {
    const code = stripComments(SIM);
    for (const tier of ["WebGPU (compute shader)", "WebGL2 (GPGPU)",
                        "WASM (Rust, 907 B)"]) {
      expect(code, `${tier} is not a benchmarked tier`).toContain(tier);
    }
    // Each must be compared against the SAME target, so no tier can be adopted
    // on easier terms than the others.
    const cmp = code.match(/>= target/g) ?? [];
    expect(cmp.length).toBe(3);
  });

  it("a tier is recorded at most once, whatever throws", () => {
    // `dispose()` throwing after a good benchmark lands in the same catch as
    // `init()` throwing, so a naive push produced two entries for one tier --
    // a duplicate React key, and the reader shown that tier twice, once with a
    // rate and once with an error.
    const code = stripComments(SIM);
    expect(code).toMatch(/private record\(t: TierTrial\)/);
    expect(code).toMatch(/this\.trials\.some\(\(x\) => x\.tier === t\.tier\)/);
    // Belt and braces: the panel must not key on tier alone either.
    expect(stripComments(BB84)).not.toMatch(/key=\{t\.tier\}/);
  });

  it("a tier that was adopted and then failed stops reading as adopted", () => {
    // The revert path restarted the CPU worker but left the record saying
    // adopted, so the panel showed "WebGPU -- adopted" in green beside a badge
    // reading "Worker (CPU)", permanently: tryUpgrade runs once per instance.
    const code = stripComments(SIM);
    expect(code).toMatch(/private revertTier\(/);
    expect(code).toMatch(/t\.adopted = false;/);
    for (const site of ["WebGPU runRound failed", "WebGL runRound failed"]) {
      const i = code.indexOf(site);
      expect(i, site).toBeGreaterThan(-1);
      expect(code.slice(i, i + 300),
        `${site} reverts without correcting the record`).toMatch(/revertTier\(/);
    }
  });

  it("every update carries the record, so it cannot be emitted without it", () => {
    // The emit() wrapper exists so a future code path cannot call onUpdate
    // directly and drop the provenance, which is how it was lost the first
    // time.
    //
    // Comments are stripped first. A draft of this counted raw occurrences, so
    // writing a comment that merely MENTIONED `this.onUpdate(` above emit()
    // failed the suite -- a guard flagging its own documentation, the shape
    // this file was written to stop.
    //
    // It also missed the regression it names. Counting calls alone passes on
    //     const cb = this.onUpdate;
    //     cb({ ...r, engine, tierTrials: [], workerPulsesPerSec: null });
    // which was verified to make the panel vanish while the count stayed at 1.
    // So the alias is forbidden too: any reference that is not the single call
    // inside emit() is a way out of the wrapper.
    const code = stripComments(SIM);
    const calls = code.match(/this\.onUpdate\(/g) ?? [];
    expect(calls.length, "onUpdate is called from more than one site; route "
      + "it through emit() so the tier record cannot be omitted").toBe(1);
    const refs = code.match(/this\.onUpdate\b/g) ?? [];
    expect(refs.length, "this.onUpdate is referenced without being called -- an "
      + "alias can emit an update that bypasses emit() and carries no tier "
      + "record, which a call count cannot see").toBe(1 + 1); // the field decl
    expect(code).toMatch(/private emit\(/);
  });

  it("the page renders the panel and does not hide it behind a tooltip only", () => {
    expect(BB84).toContain("Accelerator selection (measured in your browser");
    expect(BB84).toMatch(/tierTrials\.map\(/);
    expect(BB84).toMatch(/slower, not adopted/);
  });

  it("the export carries it too, since that is the citable artefact", () => {
    expect(BB84).toMatch(/accelerator_trials:\s*tierTrials/);
  });
});
