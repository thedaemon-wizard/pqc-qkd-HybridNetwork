/**
 * /physics's key-rate panel is the Lo-Ma two-decoy closed form. It used to be
 * captioned "the asymptotic bound, an upper bound on the finite-key rate the
 * KMEs report". That holds at the shipped block size and parameters, and
 * fails at large blocks: the finite-key model (Lim et al. 2014, a different
 * decoy analysis) is not bounded by Lo-Ma near the QBER at which key stops,
 * and its own large-block QBER tolerance is higher than Lo-Ma's (about 6.06 %
 * against 5.96 % at 17 dB). The caption now claims only the first part; this
 * pins both halves, so neither can quietly change under the words.
 */
import { describe, expect, it } from "vitest";

import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { asymptoticSkrPerPulse, BUNDLED_PARAMS, skrBpsForLink, transmittanceFromLossDb } from "./keyrate";
import { LARGE_BLOCK_N } from "./protocolLab/rates";

const HERE = dirname(fileURLToPath(import.meta.url));
const PAGE = readFileSync(join(HERE, "..", "..", "pages", "PhysicsParams.tsx"), "utf8");

const p = BUNDLED_PARAMS;
/**
 * The grid the claim was checked on: every 0.5 dB to 30 dB (past the shipped
 * cut-off near 20 dB) and every 0.25 % of misalignment to 10 % (past the ~6 %
 * at which either model stops giving key).
 */
const LOSS_MAX_DB = 30, LOSS_STEP_DB = 0.5, ED_MAX = 0.1, ED_STEP = 0.0025;

/** Points where the finite-key rate at `blockSizeN` exceeds Lo-Ma, per pulse. */
function finiteAboveLoMa(blockSizeN: number): number {
  let n = 0;
  for (let loss = 0; loss <= LOSS_MAX_DB; loss += LOSS_STEP_DB) {
    for (let eD = 0; eD <= ED_MAX; eD += ED_STEP) {
      const etaTotal = p.detectorEfficiency * transmittanceFromLossDb(loss);
      const Y0 = p.darkCountRateHz / p.pulseRateHz;
      const loMa = asymptoticSkrPerPulse({
        Y0, etaTotal, eD, mu: p.intensitySignalMu, nu1: p.intensityDecoy1Nu1,
        nu2: p.intensityDecoy2Nu2, fEC: p.ecEfficiencyF,
      });
      const finite = skrBpsForLink({ ...p, blockSizeN, misalignmentErrorEd: eD }, { lossDb: loss })
        / p.pulseRateHz;
      if (finite > Math.max(loMa, 0)) n++;
    }
  }
  return n;
}

describe("Lo-Ma against the finite-key rate", () => {
  it("lies above it at the shipped block size and parameters", () => {
    expect(finiteAboveLoMa(p.blockSizeN)).toBe(0);
  });

  it("does not bound it at a large block, so the caption must not call it an upper bound", () => {
    expect(finiteAboveLoMa(LARGE_BLOCK_N)).toBeGreaterThan(0);
  });
});

describe("what /physics says about it", () => {
  it("qualifies the comparison with the shipped block size", () => {
    expect(PAGE).not.toMatch(/an upper bound on the finite-key rate/);
    expect(PAGE).toMatch(/at the shipped block size and parameters is lower/);
    expect(PAGE).toMatch(/not that rate&apos;s large-block limit/);
  });
});
