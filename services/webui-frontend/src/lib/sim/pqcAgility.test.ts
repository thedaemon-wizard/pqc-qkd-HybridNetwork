/**
 * Algorithm agility needs somewhere to move TO.
 *
 * The page offered ML-KEM and ML-DSA and called that a crypto-agility matrix.
 * Both are module-lattice schemes: a structural break in that family takes out
 * every option at once, so being able to switch between them is motion without
 * escape. RFC 7696 is about being able to move; the point is having a
 * destination that fails independently.
 *
 * SLH-DSA (FIPS 205) is hash-based and is that destination. These tests pin
 * the sizes against the published standard -- a wrong parameter set still
 * signs and verifies perfectly well, so round-trip success proves nothing
 * about which algorithm you actually got.
 */
import { beforeAll, describe, expect, it } from "vitest";

import { SIG_NAMES, sigRoundtrip, type SigName, type SigResult } from "./pqc";

/**
 * Round-trips are computed once and shared.
 *
 * Measured on this machine: ML-DSA lands in 9-40 ms, but SLH-DSA's
 * small-signature sets take 1.1-2.2 s each. Recomputing them per assertion --
 * which the first version of this file did -- exceeded vitest's 5 s default
 * and read as three mysterious timeouts rather than as "this algorithm is
 * genuinely slow".
 */
const RESULTS = new Map<SigName, SigResult>();
const SLOW_MS = 120_000;

beforeAll(() => {
  for (const n of SIG_NAMES) RESULTS.set(n, sigRoundtrip(n));
}, SLOW_MS);

const got = (n: SigName): SigResult => {
  const r = RESULTS.get(n);
  if (!r) throw new Error(`no result for ${n}`);
  return r;
};

/**
 * FIPS 205 Table 2, and FIPS 204 Table 2.
 *
 * Public key and signature sizes in bytes. Taken from the standards, not from
 * running the code and recording what it produced -- a golden vector copied
 * from the implementation only proves the implementation equals itself.
 */
const PUBLISHED = {
  "ML-DSA-44": { standard: "FIPS 204", family: "module-lattice", pk: 1312, sig: 2420 },
  "ML-DSA-65": { standard: "FIPS 204", family: "module-lattice", pk: 1952, sig: 3309 },
  "ML-DSA-87": { standard: "FIPS 204", family: "module-lattice", pk: 2592, sig: 4627 },
  "SLH-DSA-SHA2-128s": { standard: "FIPS 205", family: "hash-based", pk: 32, sig: 7856 },
  "SLH-DSA-SHA2-128f": { standard: "FIPS 205", family: "hash-based", pk: 32, sig: 17088 },
  "SLH-DSA-SHA2-192s": { standard: "FIPS 205", family: "hash-based", pk: 48, sig: 16224 },
  "SLH-DSA-SHA2-256s": { standard: "FIPS 205", family: "hash-based", pk: 64, sig: 29792 },
} as const satisfies Record<string, { standard: string; family: string; pk: number; sig: number }>;

describe("every offered signature scheme matches its published parameters", () => {
  it("offers exactly the schemes this test knows about", () => {
    // Guards the guard: adding a scheme without adding its published sizes
    // would otherwise leave it silently unchecked.
    expect([...SIG_NAMES].sort()).toEqual(Object.keys(PUBLISHED).sort());
  });

  it.each(Object.keys(PUBLISHED) as SigName[])("%s", (name) => {
    const spec = PUBLISHED[name as keyof typeof PUBLISHED];
    const r = got(name);

    expect(r.standard).toBe(spec.standard);
    expect(r.family).toBe(spec.family);
    expect(r.publicKeyLen).toBe(spec.pk);
    expect(r.signatureLen).toBe(spec.sig);

    expect(r.verified).toBe(true);
    expect(r.rejectsTamperedMessage).toBe(true);
  });
});

describe("the agility argument the page is making", () => {
  it("offers a signature family that is not module-lattice", () => {
    // The property that makes the matrix worth having. If this ever fails,
    // every algorithm on the page shares one hardness assumption again.
    const families = new Set(SIG_NAMES.map((n) => got(n).family));
    expect(families.size).toBeGreaterThan(1);
    expect(families).toContain("hash-based");
    expect(families).toContain("module-lattice");
  });

  it("labels FIPS 205 schemes as FIPS 205", () => {
    // `standard` was a hardcoded "FIPS 204" literal in sigRoundtrip. That was
    // true while ML-DSA was the only family and would have mislabelled every
    // SLH-DSA result on the day one was added.
    const slh = SIG_NAMES.filter((n) => n.startsWith("SLH-DSA"));
    expect(slh.length).toBeGreaterThan(0);
    for (const n of slh) expect(got(n).standard).toBe("FIPS 205");
  });

  it("covers NIST categories 1, 3 and 5", () => {
    const cats = new Set(SIG_NAMES.map((n) => got(n).category));
    for (const c of [1, 3, 5]) expect(cats).toContain(c);
  });

  it("shows the size cost of leaving the lattice", () => {
    // Not incidental: SLH-DSA signatures are an order of magnitude larger, and
    // that is the reason a deployment cannot simply default to the safer
    // assumption. Worth asserting so the tradeoff stays visible.
    const mldsa = got("ML-DSA-65");
    const slhdsa = got("SLH-DSA-SHA2-192s");
    expect(slhdsa.signatureLen).toBeGreaterThan(mldsa.signatureLen * 4);
    expect(slhdsa.publicKeyLen).toBeLessThan(mldsa.publicKeyLen);
  });
});
