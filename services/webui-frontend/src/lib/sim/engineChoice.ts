/**
 * Describing how the BB84 compute tier was chosen.
 *
 * Lives here rather than in `pages/BB84.tsx` because that module imports
 * `react-plotly.js`, which touches `self` at import time and cannot be loaded
 * in the node test environment. Pure formatting has no reason to be behind a
 * charting dependency.
 */
import type { TierTrial } from "./bb84Sim";

const M = (pps: number) => `${(pps / 1e6).toFixed(1)}M/s`;

/**
 * One line naming every tier that was tried and what it scored.
 *
 * The selection is measured -- a CPU Web Worker starts immediately, then
 * WebGPU and WebGL2 are benchmarked and adopted only on a 15 % win -- and the
 * outcome used to go to `console.info` alone. The page therefore showed
 * `Worker (CPU)` with nothing to indicate a compute shader had been built,
 * initialised, run and beaten. That reads as "no GPU path exists", which is
 * false.
 */
export function engineChoiceSummary(trials: TierTrial[],
                                    workerPps: number | null): string {
  if (trials.length === 0) return "Accelerator benchmark has not run yet.";
  const cpu = workerPps === null ? "unknown" : M(workerPps);
  const parts = trials.map((t) =>
    t.pulsesPerSec === null
      ? `${t.tier}: ${t.error ?? "no result"}`
      : `${t.tier}: ${M(t.pulsesPerSec)}`
        + (t.adopted ? " (adopted)" : " (slower than CPU, not adopted)"));
  return `CPU worker ${cpu}. ` + parts.join(". ") + ".";
}
