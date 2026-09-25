/**
 * The /verify agility panel ran one implementation and called it evidence.
 *
 * `agilityMatrix()` sat in `lib/sim/pqc.ts` with zero call sites for the whole
 * project. The reason was sound and is recorded in the backend: swapping the
 * server call for it would falsify the panel heading, which names liboqs.
 * Running BOTH does not, so this cross-check is additive.
 *
 * What these tests protect is the honesty of the split. A cross-check that
 * reports "agree" when nothing was compared, or that treats byte-length
 * agreement as interoperability, is worse than no cross-check.
 */
import { describe, expect, it } from "vitest";

import { readFileSync } from "node:fs";
import { join } from "node:path";

// Each call runs the FULL matrix, including four SLH-DSA parameter sets.
// Measured at 5.9 s on a desktop, so vitest's 5 s default times out. That
// cost is also why /verify runs this on a button rather than on mount.
const SLOW = 60_000;

import { assumptionOf, crossCheckAgility, fipsName, type ServerRow } from "./agilityCrossCheck";

const REPO = join(new URL(".", import.meta.url).pathname, "../../../../..");

/** Shape of one real row, taken from the deployed demo's response. */
const KEM: ServerRow = {
  algo: "ML-KEM-768", family: "KEM", enabled: true, ok: true,
  pk_len: 1184, ct_len: 1088, ss_len: 32,
};
const SIG: ServerRow = {
  algo: "ML-DSA-65", family: "SIG", enabled: true, ok: true,
  pk_len: 1952, sig_len: 3309, rejects_tampered: true,
};

describe("it actually compares two implementations", () => {
  it("finds the algorithms both sides ran", () => {
    const r = crossCheckAgility([KEM, SIG]);
    expect(r.compared.map((c) => c.algo).sort())
      .toEqual(["ML-DSA-65", "ML-KEM-768"]);
    expect(r.allBothPass).toBe(true);
  }, SLOW);

  it("the browser half really ran -- these are not echoes of the input", () => {
    // If the client half were stubbed, flipping the SERVER verdict would still
    // leave bothPass true. It must not.
    const r = crossCheckAgility([{ ...KEM, ok: false }]);
    const row = r.compared.find((c) => c.algo === "ML-KEM-768")!;
    expect(row.clientPass, "the in-browser round-trip did not pass").toBe(true);
    expect(row.serverPass).toBe(false);
    expect(row.bothPass).toBe(false);
    expect(r.allBothPass).toBe(false);
  }, SLOW);

  it("real FIPS lengths agree, and a wrong one is caught by field name", () => {
    expect(crossCheckAgility([KEM]).allLengthsAgree).toBe(true);
    const bad = crossCheckAgility([{ ...KEM, ct_len: 1087 }]);
    expect(bad.allLengthsAgree).toBe(false);
    expect(bad.compared[0].lengthNotes.join()).toMatch(/ct_len: liboqs 1087/);
  }, SLOW);
});

describe("absence is never rendered as agreement", () => {
  it("an unreachable backend does not report everything as agreeing", () => {
    // `.every` on an empty array is true. Without the length guard this would
    // paint two green rows on a page with no server data at all.
    const r = crossCheckAgility(null);
    expect(r.compared).toHaveLength(0);
    expect(r.allBothPass).toBe(false);
    expect(r.allLengthsAgree).toBe(false);
  }, SLOW);

  it("but the browser half still ran, and says which algorithms it covered", () => {
    const r = crossCheckAgility(null);
    expect(r.clientOnly.length).toBeGreaterThan(5);
    expect(r.clientOnly).toContain("ML-KEM-768");
    expect(r.clientOnly).toContain("SLH-DSA-SHA2-128s");
  }, SLOW);

  it("a field only one side reports is 'not compared', not 'agrees'", () => {
    // A KEM row carries no sig_len. Counting that as agreement would inflate
    // the weak check with comparisons that never happened.
    const r = crossCheckAgility([KEM]);
    expect(r.compared[0].lengthsAgree).toBe(true);   // pk/ct/ss did compare
    const empty = crossCheckAgility([
      { algo: "ML-KEM-768", family: "KEM", enabled: true, ok: true },
    ]);
    expect(empty.compared[0].lengthsAgree,
      "no lengths were reported, so there is nothing to agree about").toBeNull();
  }, SLOW);

  it("names what each side ran alone rather than dropping it", () => {
    const r = crossCheckAgility([
      KEM, { algo: "Kyber512", family: "KEM", enabled: true, ok: true },
    ]);
    expect(r.serverOnly).toEqual(["Kyber512"]);
    expect(r.clientOnly).not.toContain("ML-KEM-768");
  }, SLOW);
});

describe("a signature must do both halves to count as passing", () => {
  it("verifying is not enough on its own", async () => {
    // The client verdict is `verified && rejectsTamperedMessage`. An
    // implementation that verifies everything passes the first and fails the
    // second, which is exactly the case worth catching.
    const { agilityMatrix } = await import("./pqc");
    const sig = agilityMatrix().sigs.find((s) => s.algo === "ML-DSA-65")!;
    expect(sig.verified).toBe(true);
    expect(sig.rejectsTamperedMessage).toBe(true);
    expect(crossCheckAgility([SIG]).compared[0].clientPass).toBe(true);
  }, SLOW);
});

describe("the server's signature half must include its negative control", () => {
  it("a signature row without rejects_tampered is not credited, and is named", () => {
    // One matrix run for all three cases: each call costs seconds.
    const { rejects_tampered: _dropped, ...noField } = SIG;
    const r = crossCheckAgility([
      noField,
      { ...SIG, algo: "ML-DSA-87", pk_len: 2592, sig_len: 4627, rejects_tampered: false },
      KEM,
    ]);
    const by = Object.fromEntries(r.compared.map((c) => [c.algo, c]));
    expect(by["ML-DSA-65"].serverPass, "credited a tamper check the server never reported").toBe(false);
    expect(r.serverTamperNotReported).toEqual(["ML-DSA-65"]);
    expect(by["ML-DSA-87"].serverPass, "a server that accepted a tampered message passed").toBe(false);
    expect(by["ML-KEM-768"].serverPass).toBe(true);   // KEMs have no such field
    expect(r.allBothPass).toBe(false);
  }, SLOW);
});

describe("SLH-DSA rows meet across the two spellings", () => {
  it("maps liboqs's names onto FIPS 205's", () => {
    expect(fipsName("SLH_DSA_PURE_SHA2_128S")).toBe("SLH-DSA-SHA2-128s");
    expect(fipsName("SLH_DSA_PURE_SHAKE_256F")).toBe("SLH-DSA-SHAKE-256f");
    expect(fipsName("ML-KEM-768")).toBe("ML-KEM-768");
  });

  it("so the hash-based family is actually compared", () => {
    const r = crossCheckAgility([{
      algo: "SLH_DSA_PURE_SHA2_128S", family: "SIG", enabled: true, ok: true,
      pk_len: 32, sig_len: 7856, rejects_tampered: true,
    }]);
    const row = r.compared.find((c) => c.algo === "SLH-DSA-SHA2-128s");
    expect(row, "no SLH-DSA row was compared").toBeDefined();
    expect(row!.serverAlgo).toBe("SLH_DSA_PURE_SHA2_128S");
    expect(row!.bothPass).toBe(true);
    expect(row!.lengthsAgree).toBe(true);
    expect(r.serverOnly).not.toContain("SLH_DSA_PURE_SHA2_128S");
    expect(r.clientOnly).not.toContain("SLH-DSA-SHA2-128s");
  }, SLOW);

  it("names the hardness assumption per family", () => {
    expect(assumptionOf("ML-KEM-512")).toMatch(/lattice/);
    expect(assumptionOf("HQC-3")).toMatch(/codes/);
    expect(assumptionOf("SLH_DSA_PURE_SHA2_192S")).toMatch(/hash/);
    expect(assumptionOf("Kyber512")).toBeNull();
  });

  it("has an assumption for every algorithm the validator runs by default", () => {
    // Read from the validator itself, so a family added there without a line
    // here shows up as a failure rather than as "not recorded" on /verify --
    // which is how HQC first appeared on the deployed page.
    const src = readFileSync(join(REPO, "services/pqc-validator/app/main.py"), "utf8");
    const names = ["DEFAULT_KEM_ALGOS", "DEFAULT_SIG_ALGOS"].flatMap((v) => {
      const m = new RegExp(`^${v}\\s*=\\s*\\[([\\s\\S]*?)\\]`, "m").exec(src);
      expect(m, `${v} not found`).not.toBeNull();
      return [...m![1].matchAll(/"([^"]+)"/g)].map((x) => x[1]);
    });
    expect(names.length).toBeGreaterThanOrEqual(13);
    expect(names.filter((n) => assumptionOf(n) === null)).toEqual([]);
  });
});
