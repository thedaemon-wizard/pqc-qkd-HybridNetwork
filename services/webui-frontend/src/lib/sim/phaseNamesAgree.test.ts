/**
 * The topology legend and the simulator must name the same phases.
 *
 * `MultiHopTopologySvg` carried its own copy of the phase labels, and it had
 * copied them from the wrong page -- the four `/e2e` names, verbatim from
 * `QuantumSecureE2E.tsx`, in a figure driven by `/paper-flow`'s five-phase
 * counter. Lit by strict index equality, so:
 *
 *   phase 3  legend "PQC Handshake"     inspector "WireGuard hop handshake"
 *   phase 4  legend "Data Exchange"     inspector "Rosenpass PQC handshake"
 *   phase 5  nothing lit at all         inspector "Final data tunnel + ..."
 *
 * At phase 4 the figure drew the red end-to-end data tunnel while the row
 * beside it said the Rosenpass handshake was running.
 *
 * That SVG is the PNG and GIF export target (`#paper-flow-topology-svg`), so
 * the disagreement did not stay on the page -- it was exported as evidence.
 *
 * The legend is now derived from `PHASE_BUDGETS`. This file pins that, and
 * pins the abbreviation table against the full names, because a `shortName`
 * is allowed to be shorter but not to be a different claim.
 */
import { describe, expect, it } from "vitest";

import { readFileSync } from "node:fs";
import { join } from "node:path";

import { PHASE_NAMES } from "./paperSim";

const HERE = new URL(".", import.meta.url).pathname;
const SVG = readFileSync(
  join(HERE, "../../components/MultiHopTopologySvg.tsx"), "utf8");
const E2E = readFileSync(
  join(HERE, "../../pages/QuantumSecureE2E.tsx"), "utf8");

describe("the topology legend comes from the simulator", () => {
  it("covers every phase the simulator has", () => {
    expect(PHASE_NAMES.map((p) => p.phase)).toEqual([1, 2, 3, 4, 5]);
  });

  it("the SVG derives the legend instead of restating it", () => {
    expect(SVG).toContain("PHASE_NAMES.map(");
    expect(SVG, "the legend is a literal array again").not.toMatch(
      /\{\s*idx:\s*1\s*,\s*label:/);
  });

  it("does not contain the /e2e phase names", () => {
    // The specific strings that were pasted in. `Quantum Plane` is shared
    // legitimately -- both pages really do call phase 1 that -- so it is not
    // in this list.
    for (const stolen of ["QKD Key IDs", "PQC Handshake", "Data Exchange"]) {
      expect(SVG, `${stolen} is an /e2e label, not a /paper-flow one`)
        .not.toContain(`"${stolen}"`);
    }
  });

  it("the /e2e labels it was copied from still exist, so this stays meaningful", () => {
    // If /e2e renames its phases, the assertion above starts passing for the
    // wrong reason. Pin the source so that shows up here.
    expect(E2E).toContain("3. PQC Handshake (HKDF-SHA3)");
    expect(E2E).toContain("4. Data Exchange (ChaCha20-Poly1305)");
  });
});

describe("the abbreviations are abbreviations, not different claims", () => {
  it.each(PHASE_NAMES)("phase $phase: $shortName abbreviates $name",
    ({ name, shortName }) => {
      expect(shortName.length).toBeGreaterThan(0);
      expect(shortName.length).toBeLessThanOrEqual(name.length);

      // Every significant word of the short form must appear in the full name.
      // Catches a short name that says something the full one does not --
      // which is exactly how the legend drifted last time.
      const full = name.toLowerCase();
      for (const word of shortName.toLowerCase().split(/[^a-z0-9_]+/)) {
        if (word.length < 4) continue;          // "hop", "key", "id"
        expect(full, `"${word}" is not in "${name}"`).toContain(word);
      }
    });

  it("no two phases share a short name", () => {
    const shorts = PHASE_NAMES.map((p) => p.shortName);
    expect(new Set(shorts).size).toBe(shorts.length);
  });
});
