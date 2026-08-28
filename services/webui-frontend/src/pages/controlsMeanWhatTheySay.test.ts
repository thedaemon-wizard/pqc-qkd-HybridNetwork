/**
 * Controls and captions must describe what they actually do.
 *
 * Four separate cases, all found by reading the code against the screen rather
 * than by anything failing:
 *
 *  1. `/pqc` titled its result panels from the PICKER while filling them from
 *     the last RUN, so changing the dropdown without pressing Run put one
 *     algorithm's name over another's key sizes and a green tick. The CSV
 *     export used the result and was right -- screen and export disagreed.
 *  2. `/e2e` Abort said it wipes derived key material and zeroed the buffers,
 *     but left `last_qkd_key_id` and `last_psk_prefix_hex` set -- which are
 *     exactly the two things the page renders. The export even carries the
 *     fallback text "(none - no key material survived)", which could never
 *     appear.
 *  3. `/physics` accepted any number in any field, then rendered the result:
 *     a negative link length gives eta_total > 1 and more than one secret bit
 *     per pulse, styled identically to a real figure.
 *  4. `/physics` captioned its panel "from the current parameters" while
 *     reading ten of the fourteen shown.
 *
 * None of these could fail a test: every one is a string or a missing bound.
 */
import { describe, expect, it } from "vitest";

import { readFileSync } from "node:fs";
import { join } from "node:path";

const HERE = new URL(".", import.meta.url).pathname;
const src = (p: string) => readFileSync(join(HERE, p), "utf8");

const PQC = src("PQCValidator.tsx");
const PHYSICS = src("PhysicsParams.tsx");
const VERIFY = src("Verification.tsx");
const E2ESIM = src("../lib/sim/e2eSim.ts");

// --------------------------------------------------------------------------
// 1. /pqc titles come from the result.
// --------------------------------------------------------------------------

describe("the /pqc result panels are titled by what they show", () => {
  it("the KEM panel title reads the result, not the picker", () => {
    expect(PQC).toContain("KEM — ${kem?.algo ?? kemName}");
    expect(PQC).not.toContain("KEM — ${kemName}$");
  });

  it("the signature panel title reads the result, not the picker", () => {
    expect(PQC).toContain("Signature — ${sig?.algo ?? sigName}");
    expect(PQC).not.toContain("Signature — ${sigName}$");
  });

  it("changing either picker discards the stale result", () => {
    expect(PQC).toMatch(/useEffect\(\s*\(\)\s*=>\s*\{\s*setKem\(null\);.*\}, \[kemName\]\)/s);
    expect(PQC).toMatch(/useEffect\(\s*\(\)\s*=>\s*\{\s*setSig\(null\);\s*\}, \[sigName\]\)/s);
  });

  it("the export still keys off the result, as it always did", () => {
    expect(PQC).toMatch(/kem\.algo/);
    expect(PQC).toMatch(/sig\.algo/);
  });
});

// --------------------------------------------------------------------------
// 2. Abort wipes what the page renders.
// --------------------------------------------------------------------------

describe("/e2e Abort wipes the identifiers the page displays", () => {
  it("clearKeyMaterial clears the rendered strings, not only the buffers", () => {
    const fn = E2ESIM.slice(E2ESIM.indexOf("private clearKeyMaterial"));
    const body = fn.slice(0, fn.indexOf("\n  }") + 4);
    expect(body).toContain("this.qkdKey.fill(0)");
    expect(body, "the buffers were zeroed while the rendered ids survived")
      .toContain("last_qkd_key_id");
    expect(body).toContain("last_psk_prefix_hex");
  });

  it("the export's no-key-material fallback is now reachable", () => {
    // It reads `s.last_psk_prefix_hex || "(none - ...)"`. With the field never
    // cleared, the left side was always truthy after a first cycle.
    expect(src("QuantumSecureE2E.tsx")).toContain("no key material survived");
  });
});

// --------------------------------------------------------------------------
// 3 & 4. /physics bounds and caption.
// --------------------------------------------------------------------------

describe("/physics refuses values the physics has no meaning for", () => {
  it("every numeric parameter has a bound entry", () => {
    const labels = [...PHYSICS.matchAll(/^\s*"([a-z_]+\.[a-z0-9_]+)":\s*"/gm)]
      .map((m) => m[1]);
    const bounded = new Set(
      [...PHYSICS.matchAll(/^\s*"([a-z_]+\.[a-z0-9_]+)":\s*\[/gm)].map((m) => m[1]));
    // eve.enabled is a checkbox, not a number.
    const numeric = labels.filter((l) => l !== "eve.enabled");
    const missing = numeric.filter((l) => !bounded.has(l));
    expect(missing, "unbounded numeric parameters").toEqual([]);
  });

  it("probabilities are capped at 1", () => {
    for (const k of ["physical.detector_efficiency", "source.basis_bias_pz",
                     "eve.intercept_prob"]) {
      expect(PHYSICS).toMatch(new RegExp(`"${k.replace(".", "\\.")}": \\[0, 1\\]`));
    }
  });

  it("error-correction efficiency cannot beat the Shannon limit", () => {
    expect(PHYSICS).toMatch(/"protocol\.ec_efficiency_f": \[1, null\]/);
  });

  it("the input both declares the bound and enforces it", () => {
    // `min`/`max` alone style the field and block the spinner; a typed or
    // pasted value still reaches onChange.
    expect(PHYSICS).toContain("min={BOUNDS[field.path]?.[0]");
    expect(PHYSICS).toContain("max={BOUNDS[field.path]?.[1]");
    expect(PHYSICS).toMatch(/if \(lo !== null && n < lo\) return;/);
    expect(PHYSICS).toMatch(/if \(hi !== null && n > hi\) return;/);
  });
});

describe("/physics says which parameters its panel reads", () => {
  it("the caption no longer claims all of them", () => {
    expect(PHYSICS).not.toContain(
      "Computed in the browser from the current parameters — no backend call.");
    expect(PHYSICS).toContain("parameters this panel reads");
  });

  it("the declared set matches what the computation destructures", () => {
    const block = /CLIENT_SIDE_INPUTS = new Set\(\[([\s\S]*?)\]\)/.exec(PHYSICS);
    expect(block, "CLIENT_SIDE_INPUTS is gone").not.toBeNull();
    const declared = new Set(
      [...block![1].matchAll(/"([^"]+)"/g)].map((m) => m[1]));
    for (const k of declared) {
      expect(PHYSICS, `${k} is declared as read but never used`)
        .toContain(`pv("${k}")`);
    }
    expect(declared.size).toBe(10);
  });

  it("the five it does not read are named so the reader is not left guessing", () => {
    for (const word of ["basis bias", "QBER abort threshold", "batch size", "Eve"]) {
      expect(PHYSICS.toLowerCase()).toContain(word.toLowerCase());
    }
  });
});

// --------------------------------------------------------------------------
// 5. The agility panel names every family it runs.
// --------------------------------------------------------------------------

describe("the /verify agility panel names all three families", () => {
  it("SLH-DSA is in the title", () => {
    expect(VERIFY).toContain("ML-KEM, ML-DSA, SLH-DSA");
    expect(VERIFY).not.toContain("Matrix (liboqs — ML-KEM + ML-DSA)");
  });

  it("the prose lists the SLH-DSA parameter sets too", () => {
    expect(VERIFY).toContain("SLH-DSA-SHA2 128s/192s/256s");
  });
});
