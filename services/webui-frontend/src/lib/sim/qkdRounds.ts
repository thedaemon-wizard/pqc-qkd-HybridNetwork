/**
 * One round of BB84, BBM92 or MDI-QKD, for the walk-through on /qkd-protocols.
 *
 * IDEALISED, and the page says so: one photon or one pair, no loss, no noise, no
 * eavesdropper. It shows the logic of a round: what each party prepares, what is
 * announced, what is thrown away. It is not a rate, a security test or a key
 * generator, and it keeps no count of bits. The rates are protocolRates.ts.
 *
 * Polarisation labels are the usual ones: Z basis 0 = H, 1 = V; X basis 0 = D,
 * 1 = A. MDI's outcomes and Bob's flip are Lo, Curty and Qi (2012), Table I, and
 * tests/test_protocol_rates.py derives the probabilities from linear optics.
 */

export type RoundProtocol = "bb84" | "bbm92" | "mdi";
export type Basis = "Z" | "X";
export type Bit = 0 | 1;
export type RelayResult = "psi-" | "psi+" | "none";

export const PROTOCOL_NAMES: Record<RoundProtocol, string> = {
  bb84: "BB84 (prepare and measure)",
  bbm92: "BBM92 (entanglement-based)",
  mdi: "MDI-QKD (untrusted relay)",
};

/** What each part of a round is, in order. */
export const ROUND_PARTS: Record<RoundProtocol, readonly string[]> = {
  bb84: ["Alice prepares a state", "The photon crosses the fibre", "Bob measures", "They compare bases", "Keep or discard"],
  bbm92: ["The source emits a pair", "One photon goes each way", "Both measure", "They compare bases", "Keep or discard"],
  mdi: ["Alice and Bob each prepare", "The photons meet at the relay", "The relay announces", "They compare bases", "Bob flips, or not", "Keep or discard"],
};

export interface Round {
  protocol: RoundProtocol;
  alice: { basis: Basis; bit: Bit };
  bob: { basis: Basis; bit: Bit };
  relay: RelayResult | null;
  /** MDI: whether Table I has Bob flip his bit for this outcome. */
  flip: boolean;
  /** The bases agree, and in MDI the relay announced a success. */
  kept: boolean;
  /** The shared bit, when the round is kept. */
  key: Bit | null;
  why: string;
}

export const stateLabel = (basis: Basis, bit: Bit): string =>
  basis === "Z" ? (bit === 0 ? "H" : "V") : (bit === 0 ? "D" : "A");

/**
 * The relay's outcome for two single photons that both arrive, with no noise.
 * Linear optics identifies only psi- and psi+ (Lo, Curty and Qi, Fig. 1).
 */
export function mdiOutcomes(a: Basis, aBit: Bit, b: Basis, bBit: Bit): Record<RelayResult, number> {
  if (a !== b) return { "psi+": 0.25, "psi-": 0.25, none: 0.5 };
  if (a === "Z") return aBit === bBit ? { "psi+": 0, "psi-": 0, none: 1 } : { "psi+": 0.5, "psi-": 0.5, none: 0 };
  return aBit === bBit ? { "psi+": 0.5, "psi-": 0, none: 0.5 } : { "psi+": 0, "psi-": 0.5, none: 0.5 };
}

/** Table I: Bob flips in the Z basis, and in the X basis only on psi-. */
export const mdiBobFlips = (basis: Basis, relay: RelayResult): boolean =>
  relay !== "none" && (basis === "Z" || relay === "psi-");

const pickBasis = (u: number): Basis => (u < 0.5 ? "Z" : "X");
const pickBit = (u: number): Bit => (u < 0.5 ? 0 : 1);

/** A round from uniform draws in [0, 1), so a test can walk every case. */
export function playRound(protocol: RoundProtocol, draw: () => number): Round {
  const aBasis = pickBasis(draw());
  const bBasis = pickBasis(draw());
  if (protocol === "mdi") {
    const aBit = pickBit(draw());
    const bBit = pickBit(draw());
    const o = mdiOutcomes(aBasis, aBit, bBasis, bBit);
    const u = draw();
    const relay: RelayResult = u < o["psi-"] ? "psi-" : u < o["psi-"] + o["psi+"] ? "psi+" : "none";
    const same = aBasis === bBasis;
    const kept = same && relay !== "none";
    const flip = same && mdiBobFlips(aBasis, relay);
    return {
      protocol, alice: { basis: aBasis, bit: aBit }, bob: { basis: bBasis, bit: bBit }, relay, flip, kept,
      key: kept ? aBit : null,
      why: relay === "none" ? "the relay announced no result"
        : !same ? "the relay answered, but the bases differ"
        : flip ? "same basis, and Bob flips his bit" : "same basis, and Bob keeps his bit",
    };
  }
  const aBit = pickBit(draw());
  const same = aBasis === bBasis;
  // Same basis: Bob reads Alice's bit, or the pair's perfectly correlated bit. A
  // different basis gives him a fair coin.
  const bBit = same ? aBit : pickBit(draw());
  return {
    protocol, alice: { basis: aBasis, bit: aBit }, bob: { basis: bBasis, bit: bBit }, relay: null, flip: false,
    kept: same, key: same ? aBit : null,
    why: same ? "same basis, so the bits agree" : "the bases differ, so Bob's result says nothing",
  };
}

/** Bob's bit after any flip: on a kept round it is always Alice's. */
export const bobFinalBit = (r: Round): Bit => (r.flip ? ((1 - r.bob.bit) as Bit) : r.bob.bit);

/** The part of a round being played at progress `p` (0..1). */
export const partAt = (protocol: RoundProtocol, p: number): number =>
  Math.min(ROUND_PARTS[protocol].length - 1, Math.floor(Math.max(0, p) * ROUND_PARTS[protocol].length));

/** Where the photons are at progress `p`: x positions in [0, 1] along the line, one or two. */
export function photonPositions(protocol: RoundProtocol, p: number): number[] {
  const n = ROUND_PARTS[protocol].length;
  const u = Math.max(0, Math.min(1, (p * n - 1)));
  // Only during the second part: before it they are held, after it they are gone.
  if (p * n < 1 || p * n >= 2) return [];
  if (protocol === "bb84") return [u];
  if (protocol === "bbm92") return [0.5 - u / 2, 0.5 + u / 2];
  return [u / 2, 1 - u / 2];
}

/** A seeded draw for `?seed=`, so a reader can replay the same rounds (mulberry32). */
export function seededDraw(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
