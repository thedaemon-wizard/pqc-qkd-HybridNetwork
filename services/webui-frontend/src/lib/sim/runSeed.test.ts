/**
 * `?seed=` makes a run reproducible. Without it nothing changes.
 *
 * docs/roadmap.md already recorded the gap this closes: "every rung reseeds
 * from Math.random() each round -- so the rungs are statistically equivalent,
 * not identical, and no run is reproducible." A page whose claim is "here is
 * the physics, check it yourself" cannot hand a reader an unreproducible
 * figure.
 */
import { describe, expect, it } from "vitest";

import { RunSeeds, seedFromLocation } from "./runSeed";

describe("parsing ?seed=", () => {
  it("reads decimal and hex", () => {
    expect(seedFromLocation("?seed=1234")).toBe(1234);
    expect(seedFromLocation("?seed=0xdeadbeef")).toBe(0xdeadbeef);
  });

  it("returns null rather than NaN or a silent zero for junk", () => {
    // Number("abc") is NaN, and NaN >>> 0 is 0 -- which would silently PIN
    // every malformed link to seed 0 and look like it worked.
    for (const q of ["", "?seed=", "?seed=abc", "?seed=1.5", "?seed=-3", "?other=1"]) {
      expect(seedFromLocation(q), `${q} should not parse`).toBeNull();
    }
  });
});

describe("a pinned run replays exactly", () => {
  it("same seed, same sequence", () => {
    const a = new RunSeeds(42), b = new RunSeeds(42);
    const seqA = Array.from({ length: 8 }, () => a.next());
    const seqB = Array.from({ length: 8 }, () => b.next());
    expect(seqA).toEqual(seqB);
  });

  it("reset() replays it again, so re-running reproduces the figure", () => {
    const s = new RunSeeds(42);
    const first = Array.from({ length: 5 }, () => s.next());
    s.reset();
    expect(Array.from({ length: 5 }, () => s.next())).toEqual(first);
  });

  it("rounds differ from each other, so the history is not a flat line", () => {
    // Returning the base seed every round would make every round an identical
    // sample -- a QBER history that reads as a stuck sensor.
    const s = new RunSeeds(42);
    const seq = Array.from({ length: 16 }, () => s.next());
    expect(new Set(seq).size).toBe(16);
  });

  it("different seeds give different sequences", () => {
    const a = Array.from({ length: 4 }, ((s) => () => s.next())(new RunSeeds(1)));
    const b = Array.from({ length: 4 }, ((s) => () => s.next())(new RunSeeds(2)));
    expect(a).not.toEqual(b);
  });

  it("adjacent seeds do not give adjacent first outputs", () => {
    // A plain `base + i` would; mulberry32 and xorshift32 both correlate
    // visibly on adjacent seeds, which would put structure in the QBER
    // history that the physics did not.
    const d = Math.abs(new RunSeeds(41).next() - new RunSeeds(42).next());
    expect(d).toBeGreaterThan(1000);
  });

  it("every value is a valid uint32", () => {
    const s = new RunSeeds(0xffffffff);
    for (let i = 0; i < 32; i++) {
      const v = s.next();
      expect(Number.isInteger(v)).toBe(true);
      expect(v).toBeGreaterThanOrEqual(0);
      expect(v).toBeLessThanOrEqual(0xffffffff);
    }
  });
});

describe("the default path is unchanged", () => {
  it("unpinned runs are not reproducible, which is the previous behaviour", () => {
    const a = Array.from({ length: 8 }, ((s) => () => s.next())(new RunSeeds(null)));
    const b = Array.from({ length: 8 }, ((s) => () => s.next())(new RunSeeds(null)));
    expect(a).not.toEqual(b);
    expect(new RunSeeds(null).pinned).toBe(false);
    expect(new RunSeeds(7).pinned).toBe(true);
  });

  it("the round counter advances in both modes", () => {
    // So a round index means the same thing whether or not a seed was given.
    const s = new RunSeeds(null);
    s.next(); s.next();
    s.reset();
    expect(s.value).toBeNull();
  });
});
