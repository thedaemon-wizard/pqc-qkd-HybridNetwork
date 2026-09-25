/**
 * /pqc names the library that produced its results, in the footer and in the
 * exported run log. That name carried a hand-typed version, "0.7.0", which
 * stayed behind when the dependency moved to 0.7.1 -- every result since was
 * attributed to a release that did not produce it.
 *
 * The version is now injected at build time from the installed package
 * (vite.config.ts). This checks the injected value against the installed file
 * independently, and that no literal has come back.
 */
import { describe, expect, it } from "vitest";

import { readFileSync } from "node:fs";
import { join } from "node:path";

import { PQC_PROVIDER, POLICY_STANDING, KEM_NAMES, SIG_NAMES, policyStanding } from "./pqc";

const HERE = new URL(".", import.meta.url).pathname;
const ROOT = join(HERE, "../../..");

describe("the provider version is the installed one", () => {
  it("matches node_modules/@noble/post-quantum/package.json", () => {
    const installed = JSON.parse(readFileSync(
      join(ROOT, "node_modules/@noble/post-quantum/package.json"), "utf8")).version;
    expect(PQC_PROVIDER.version).toBe(installed);
  });

  it("matches the lockfile", () => {
    const lock = JSON.parse(readFileSync(join(ROOT, "package-lock.json"), "utf8"));
    expect(PQC_PROVIDER.version)
      .toBe(lock.packages["node_modules/@noble/post-quantum"].version);
  });

  it("is not a literal in pqc.ts", () => {
    const src = readFileSync(join(HERE, "pqc.ts"), "utf8");
    expect(src).toMatch(/version: __NOBLE_PQ_VERSION__,/);
    expect(src).not.toMatch(/version: "\d+\.\d+\.\d+"/);
  });
});

describe("every offered algorithm has a recorded policy standing", () => {
  it("covers the pickers exactly", () => {
    expect(Object.keys(POLICY_STANDING).sort()).toEqual([...KEM_NAMES, ...SIG_NAMES].sort());
  });

  it("states it with its date, not as compliance", () => {
    expect(policyStanding("ML-KEM-512")).toMatch(/not recommended.*as recorded \d{4}-\d{2}-\d{2}/);
    expect(policyStanding("ML-KEM-1024")).toMatch(/CNSA 2\.0: approved/);
  });

  it("prints BSI's condition with every BSI recommendation", () => {
    // TR-02102-1 2026-01 recommends ML-KEM and ML-DSA only in hybrid
    // combination with a classical scheme (sections 2.1, 2.4, 5.3.4); only
    // hash-based signatures may in principle be used alone. /pqc runs each
    // algorithm standalone, so a bare "recommended" misstated the guideline.
    for (const algo of ["ML-KEM-768", "ML-KEM-1024", "ML-DSA-65", "ML-DSA-87"]) {
      expect(policyStanding(algo), algo)
        .toContain("BSI TR-02102-1: recommended (hybrid with a classical scheme only)");
    }
    for (const algo of ["SLH-DSA-SHA2-192s", "SLH-DSA-SHA2-256s"]) {
      expect(policyStanding(algo), algo).toContain("BSI TR-02102-1: recommended (may be used alone)");
    }
    for (const [algo, p] of Object.entries(POLICY_STANDING)) {
      // A condition exactly when there is a recommendation to qualify.
      expect(p.bsiCondition !== null, algo).toBe(p.bsi);
      if (!p.bsi) expect(policyStanding(algo), algo).toContain("BSI TR-02102-1: not recommended ·");
    }
  });

  it("meets BSI's hedged-signing condition rather than printing it", () => {
    // BSI recommends the "hedged" ML-DSA and SLH-DSA variants. noble signs
    // hedged unless `extraEntropy: false` is passed; pqc.ts passes no options.
    const src = readFileSync(join(HERE, "pqc.ts"), "utf8");
    expect(src).toMatch(/impl\.sign\(message, secretKey\)/);
    expect(src).not.toMatch(/extraEntropy:\s*false/);
  });
});
