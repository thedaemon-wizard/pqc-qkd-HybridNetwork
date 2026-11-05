/**
 * The walk-through's logic. Each case is walked exhaustively rather than sampled,
 * and the outcome table is the one tests/test_protocol_rates.py derives from
 * linear optics.
 */
import { describe, expect, it } from "vitest";

import {
  ROUND_PARTS, bobFinalBit, mdiBobFlips, mdiOutcomes, partAt, photonPositions, playRound,
  type Basis, type Bit, type RoundProtocol,
} from "./qkdRounds";

const BASES: Basis[] = ["Z", "X"];
const BITS: Bit[] = [0, 1];

/** A draw that returns these values in turn. */
const scripted = (...v: number[]) => { let i = 0; return () => v[i++ % v.length]; };

describe("MDI-QKD's outcome table", () => {
  it("adds up to one for every input", () => {
    for (const a of BASES) for (const b of BASES) for (const x of BITS) for (const y of BITS) {
      const o = mdiOutcomes(a, x, b, y);
      expect(o["psi+"] + o["psi-"] + o.none).toBeCloseTo(1, 12);
    }
  });

  it("gives equal Z inputs no result, because the photons bunch", () => {
    expect(mdiOutcomes("Z", 0, "Z", 0)).toEqual({ "psi+": 0, "psi-": 0, none: 1 });
    expect(mdiOutcomes("Z", 1, "Z", 1).none).toBe(1);
  });

  it("gives opposite Z inputs a result every time, and X inputs half the time", () => {
    expect(mdiOutcomes("Z", 0, "Z", 1).none).toBe(0);
    expect(mdiOutcomes("X", 0, "X", 0).none).toBe(0.5);
    expect(mdiOutcomes("X", 0, "X", 1).none).toBe(0.5);
  });

  it("averages to one half over the bits, in either basis, and is not always one half", () => {
    for (const basis of BASES) {
      let sum = 0;
      for (const x of BITS) for (const y of BITS) {
        const o = mdiOutcomes(basis, x, basis, y);
        sum += 0.25 * (o["psi+"] + o["psi-"]);
      }
      expect(sum).toBeCloseTo(0.5, 12);
    }
  });

  it("has Bob flip as in Table I: always in Z, and only on psi- in X", () => {
    expect(mdiBobFlips("Z", "psi-")).toBe(true);
    expect(mdiBobFlips("Z", "psi+")).toBe(true);
    expect(mdiBobFlips("X", "psi-")).toBe(true);
    expect(mdiBobFlips("X", "psi+")).toBe(false);
    expect(mdiBobFlips("Z", "none")).toBe(false);
  });

  it("makes the two bits agree after the flip, on every outcome that can happen", () => {
    for (const basis of BASES) for (const x of BITS) for (const y of BITS) {
      const o = mdiOutcomes(basis, x, basis, y);
      for (const relay of ["psi-", "psi+"] as const) {
        if (o[relay] === 0) continue;
        const final = mdiBobFlips(basis, relay) ? 1 - y : y;
        expect(final, `${basis} ${x}${y} ${relay}`).toBe(x);
      }
    }
  });
});

describe("a round", () => {
  it("keeps BB84's bit only when the bases agree, and then Bob has it", () => {
    const kept = playRound("bb84", scripted(0.1, 0.2, 0.9));
    expect(kept.kept).toBe(true);
    expect(kept.key).toBe(1);
    expect(kept.bob.bit).toBe(1);
    const lost = playRound("bb84", scripted(0.1, 0.8, 0.9, 0.1));
    expect(lost.kept).toBe(false);
    expect(lost.key).toBeNull();
  });

  it("does the same for BBM92", () => {
    expect(playRound("bbm92", scripted(0.8, 0.9, 0.1)).key).toBe(0);
    expect(playRound("bbm92", scripted(0.8, 0.1, 0.1, 0.9)).kept).toBe(false);
  });

  it("keeps an MDI round only with the same basis and a result from the relay", () => {
    // Z, Z, Alice 0, Bob 1: a result every time.
    const z = playRound("mdi", scripted(0.1, 0.1, 0.1, 0.9, 0.2));
    expect(z.relay).toBe("psi-");
    expect(z.kept).toBe(true);
    expect(z.flip).toBe(true);
    expect(bobFinalBit(z)).toBe(z.alice.bit);
    // Z, Z, equal bits: no result, whatever the draw.
    const bunched = playRound("mdi", scripted(0.1, 0.1, 0.1, 0.1, 0.0));
    expect(bunched.relay).toBe("none");
    expect(bunched.kept).toBe(false);
    // Different bases: the relay may answer, and the round is still thrown away.
    const mixed = playRound("mdi", scripted(0.1, 0.9, 0.1, 0.1, 0.1));
    expect(mixed.relay).toBe("psi-");
    expect(mixed.kept).toBe(false);
    expect(mixed.flip).toBe(false);
  });

  it("agrees on every kept round, over many random ones", () => {
    let seed = 12345;
    const draw = () => { seed = (seed * 1664525 + 1013904223) % 2 ** 32; return seed / 2 ** 32; };
    for (const p of ["bb84", "bbm92", "mdi"] as RoundProtocol[]) {
      let kept = 0;
      for (let i = 0; i < 4000; i++) {
        const r = playRound(p, draw);
        if (r.kept) { kept += 1; expect(bobFinalBit(r)).toBe(r.alice.bit); expect(r.key).toBe(r.alice.bit); }
        else expect(r.key).toBeNull();
      }
      // One half of the rounds for BB84 and BBM92, one quarter for MDI.
      expect(kept / 4000).toBeGreaterThan(p === "mdi" ? 0.2 : 0.45);
      expect(kept / 4000).toBeLessThan(p === "mdi" ? 0.3 : 0.55);
    }
  });
});

describe("the playback of a round", () => {
  it("walks the parts in order", () => {
    const n = ROUND_PARTS.mdi.length;
    expect(partAt("mdi", 0)).toBe(0);
    expect(partAt("mdi", 0.999)).toBe(n - 1);
    expect(partAt("mdi", 1)).toBe(n - 1);
    expect(partAt("mdi", (2.5) / n)).toBe(2);
  });

  it("moves the photons only in the second part: one for BB84, two for the others", () => {
    const at = (p: RoundProtocol, u: number) => photonPositions(p, (1 + u) / ROUND_PARTS[p].length);
    expect(photonPositions("bb84", 0)).toEqual([]);
    expect(photonPositions("bb84", 0.99)).toEqual([]);
    expect(at("bb84", 0.5)).toEqual([0.5]);
    expect(at("bbm92", 0.5)).toEqual([0.25, 0.75]);
    expect(at("mdi", 0.5)).toEqual([0.25, 0.75]);
    expect(at("mdi", 0)).toEqual([0, 1]);
  });
});
