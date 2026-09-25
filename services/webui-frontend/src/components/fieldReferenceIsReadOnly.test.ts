/**
 * /physics's field-reference panel shows arXiv:2608.18869's measurements beside
 * this project's model and must never feed them into the model's parameters.
 */
import { describe, expect, it } from "vitest";

import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { presetById, quantityValue } from "../lib/sim/protocolLab/publishedNetworks";
import { fieldComparison } from "../lib/sim/protocolLab/rates";
import { gainQmu, qberEmu, BUNDLED_PARAMS, transmittanceFromLossDb } from "../lib/sim/keyrate";

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

  it("gives zero key on both links at the measured QBER, as docs/references.md states", () => {
    for (const l of links) {
      const c = fieldComparison(l)!;
      expect(c.atMeasuredQber ?? 0, l.id).toBe(0);
    }
  });

  it("really does match the measured QBER when it solves for misalignment", () => {
    const l = links.find((x) => x.id === "SND-ERF")!;
    const c = fieldComparison(l)!;
    const p = BUNDLED_PARAMS;
    const eta = p.detectorEfficiency * transmittanceFromLossDb(quantityValue(l.loss!));
    const Y0 = p.darkCountRateHz / p.pulseRateHz;
    expect(gainQmu(Y0, eta, p.intensitySignalMu)).toBeGreaterThan(0);
    expect(qberEmu(Y0, eta, c.impliedMisalignment!, p.intensitySignalMu))
      .toBeCloseTo(quantityValue(l.qber!), 10);
  });

  it("marks a lower-bound loss so the model value reads as an upper bound", () => {
    for (const l of links) expect(fieldComparison(l)!.lossIsLowerBound).toBe(true);
  });
});
