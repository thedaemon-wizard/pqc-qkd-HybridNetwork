/**
 * /physics's field-reference panel shows arXiv:2608.18869's measurements beside
 * this project's model and must never feed them into the model's parameters.
 */
import { describe, expect, it } from "vitest";

import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { presetById, quantityHalfStep, quantityValue } from "../lib/sim/protocolLab/publishedNetworks";
import { fieldComparison, LARGE_BLOCK_N } from "../lib/sim/protocolLab/rates";
import { qberEmu, BUNDLED_PARAMS, skrBpsForLink, transmittanceFromLossDb } from "../lib/sim/keyrate";
import { modelReasons } from "./FieldReferencePanel";

const HERE = dirname(fileURLToPath(import.meta.url));
const SRC = readFileSync(join(HERE, "FieldReferencePanel.tsx"), "utf8");

describe("read-only", () => {
  it("takes no props and calls no setter or request", () => {
    expect(SRC).toMatch(/export default function FieldReferencePanel\(\)/);
    expect(SRC).not.toMatch(/\bset[A-Z]\w*\(|fetch\(|useState|onChange/);
  });

  it("is mounted on /physics", () => {
    const page = readFileSync(join(HERE, "..", "pages", "PhysicsParams.tsx"), "utf8");
    expect(page).toMatch(/<FieldReferencePanel \/>/);
  });
});

describe("the comparison", () => {
  const links = presetById("thuringia-2026").links.filter((l) => l.kind === "qkd");

  it("the model's QBER tolerance at each link's loss is below that link's campaign-mean QBER", () => {
    // A property of the model at these losses, not a finding about the links:
    // the links ran at a varying QBER and distilled key in its low intervals.
    for (const l of links) {
      expect(fieldComparison(l)!.meanVsTolerance, l.id).toBe("above");
    }
  });

  it("at a large block, SND-ERF's mean is clearly above the tolerance and ERF-IOF's is level with it", () => {
    // ERF-IOF prints 6.1 %, which stands for 6.05-6.15 %, and the model's
    // large-block tolerance at 21 dB is about 6.06 %. The printed mean does
    // not settle which side it is on, and the page must not say it does.
    const by = Object.fromEntries(links.map((l) => [l.id, fieldComparison(l)!]));
    expect(by["SND-ERF"].meanVsLargeBlockTolerance).toBe("above");
    expect(by["ERF-IOF"].meanVsLargeBlockTolerance).toBe("level");
    const erf = links.find((l) => l.id === "ERF-IOF")!;
    const mean = quantityValue(erf.qber!);
    const half = quantityHalfStep(erf.qber!);
    const tol = by["ERF-IOF"].qberToleranceLargeBlock!;
    expect(tol).toBeGreaterThan(mean - half);
    expect(tol).toBeLessThan(mean + half);
  });

  it("the finite-key tolerance really is the edge: key just below it, none just above", () => {
    const p = BUNDLED_PARAMS;
    for (const l of links) {
      const c = fieldComparison(l)!;
      const lossDb = quantityValue(l.loss!);
      expect(c.toleranceMisalignment, l.id).not.toBeNull();
      const eD = c.toleranceMisalignment!;
      const at = (e: number) => skrBpsForLink({ ...p, misalignmentErrorEd: e }, { lossDb });
      expect(at(eD * 0.99), l.id).toBeGreaterThan(0);
      expect(at(eD * 1.01 + 1e-6), l.id).toBe(0);
      const eta = p.detectorEfficiency * transmittanceFromLossDb(lossDb);
      const Y0 = p.darkCountRateHz / p.pulseRateHz;
      expect(c.qberTolerance).toBeCloseTo(qberEmu(Y0, eta, eD, p.intensitySignalMu), 12);
    }
  });

  it("names the loss cut-off only where the loss is past it", () => {
    const by = Object.fromEntries(links.map((l) => [l.id, fieldComparison(l)!]));
    expect(by["SND-ERF"].pastLossCutoff).toBe(false);
    expect(by["ERF-IOF"].pastLossCutoff).toBe(true);
    // The shipped configuration distils at the cut-off and not past it.
    const p = BUNDLED_PARAMS;
    const cut = by["ERF-IOF"].lossCutoffDb;
    expect(skrBpsForLink(p, { lossDb: cut - 0.01 })).toBeGreaterThan(0);
    expect(skrBpsForLink(p, { lossDb: cut + 0.01 })).toBe(0);
  });

  it("marks a lower-bound loss so the model value reads as an upper bound", () => {
    for (const l of links) expect(fieldComparison(l)!.lossIsLowerBound).toBe(true);
  });
});

describe("the large-block tolerance", () => {
  const links = presetById("thuringia-2026").links.filter((l) => l.kind === "qkd");
  const p = BUNDLED_PARAMS;
  /** Tolerance from the same finite-key model, re-derived here at any block size. */
  const toleranceAt = (lossDb: number, blockSizeN: number): number => {
    const key = (e: number) => skrBpsForLink({ ...p, blockSizeN, misalignmentErrorEd: e }, { lossDb }) > 0;
    let lo = 0, hi = 0.5;
    for (let i = 0; i < 60; i++) { const m = (lo + hi) / 2; if (key(m)) lo = m; else hi = m; }
    const eta = p.detectorEfficiency * transmittanceFromLossDb(lossDb);
    return qberEmu(p.darkCountRateHz / p.pulseRateHz, eta, lo, p.intensitySignalMu);
  };
  /** The panel prints a tolerance as a percentage with two decimals. */
  const PRINTED_STEP = 1e-4;

  it("is at least the tolerance at the shipped block size", () => {
    for (const l of links) {
      const c = fieldComparison(l)!;
      expect(c.qberToleranceLargeBlock!, l.id).toBeGreaterThanOrEqual(c.qberTolerance!);
    }
  });

  it("does not fall as the block grows from the shipped size to LARGE_BLOCK_N", () => {
    // What "no block size gives key" leans on: the tolerance rises with the
    // block, so the large-block value is the most the model tolerates.
    for (const l of links) {
      const lossDb = quantityValue(l.loss!);
      let prev = -Infinity;
      for (let n = p.blockSizeN; n <= LARGE_BLOCK_N; n *= 10) {
        const t = toleranceAt(lossDb, n);
        expect(t, `${l.id} at N = ${n}`).toBeGreaterThanOrEqual(prev);
        prev = t;
      }
    }
  });

  it("is converged: a much larger block moves it by less than a tenth of the printed step", () => {
    for (const l of links) {
      const lossDb = quantityValue(l.loss!);
      const c = fieldComparison(l)!;
      const far = toleranceAt(lossDb, LARGE_BLOCK_N * 1e12);
      expect(Math.abs(far - c.qberToleranceLargeBlock!), l.id).toBeLessThan(PRINTED_STEP / 10);
    }
  });

  it("comes from the finite-key model, not the Lo-Ma closed form", () => {
    for (const l of links) {
      const c = fieldComparison(l)!;
      expect(c.qberToleranceLargeBlock!, l.id)
        .toBeCloseTo(toleranceAt(quantityValue(l.loss!), LARGE_BLOCK_N), 12);
    }
    const rates = readFileSync(join(HERE, "..", "lib", "sim", "protocolLab", "rates.ts"), "utf8");
    expect(rates).not.toMatch(/asymptoticSkrPerPulse/);
  });
});

describe("the wording matches the comparison", () => {
  const links = presetById("thuringia-2026").links.filter((l) => l.kind === "qkd");

  it("says no block size gives key only where the mean is clearly above the large-block tolerance", () => {
    for (const l of links) {
      const c = fieldComparison(l)!;
      const text = modelReasons(c, l).join(" ");
      if (c.meanVsLargeBlockTolerance === "above") {
        expect(text, l.id).toMatch(/no block size gives key/);
      } else {
        expect(text, l.id).not.toMatch(/no block size gives key/);
      }
      if (c.meanVsLargeBlockTolerance === "level") {
        expect(text, l.id).toMatch(/level with the model's large-block tolerance/);
        expect(text, l.id).toMatch(/does not settle/);
      }
    }
  });

  it("prints the large-block tolerance and its block size, and no asymptotic value", () => {
    const erf = links.find((l) => l.id === "ERF-IOF")!;
    const text = modelReasons(fieldComparison(erf)!, erf).join(" ");
    expect(text).toContain("6.06 % at N = 1e18");
    expect(SRC).toContain("(the model's large-block tolerance)");
    expect(SRC).not.toMatch(/asymptotic/i);
  });
});

describe("what the panel says", () => {
  it("no longer sets a zero at the mean QBER against the measured key", () => {
    expect(SRC).not.toContain("misalignment matched to the QBER");
    expect(SRC).not.toContain("the links themselves distilled");
  });

  it("states that the measured values are campaign means with temporal standard deviations", () => {
    expect(SRC).toMatch(/temporal standard deviations \(section IV\.A\)/);
  });

  it("gives a reason per link and links to the source", () => {
    expect(SRC).toContain("modelReasons(c, l)");
    expect(SRC).toContain("href={preset.meta.url}");
  });

  it("carries SND-ERF's averaging caveat from the source", () => {
    const l = presetById("thuringia-2026").links.find((x) => x.id === "SND-ERF")!;
    expect(l.notes.join(" ")).toMatch(/intervals whose QBER exceeded the security threshold produced no key/);
  });
});
