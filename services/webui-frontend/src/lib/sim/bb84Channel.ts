/**
 * The BB84 channel model, in one place, shared by all three compute tiers.
 *
 * The same per-pulse simulation is expressed three times in this directory: as
 * WGSL in `bb84Gpu.ts`, as GLSL ES in `bb84Gl.ts`, and as TypeScript in
 * `bb84.worker.ts`. That much is unavoidable -- a compute shader cannot import
 * a module. What was avoidable was everything built around them drifting:
 *
 *   - the key-pool update was written out three times, character for character,
 *     with four magic numbers and no name on any of them;
 *   - the GPU tiers displayed a photon table produced by a SEPARATE
 *     `Math.random()` pass, so the frames a viewer read were not the pulses
 *     that produced the QBER printed beside them.
 *
 * Both shaders seed a per-invocation xorshift32 from `(seed, invocationId)` and
 * are otherwise pure, which makes a GPU round exactly reproducible on the CPU.
 * So instead of inventing plausible-looking frames, `framesFromGpuRound` and
 * `framesFromGlRound` REPLAY the first invocations of the round that just ran.
 * The table then shows real pulses from the real run at no readback cost.
 */

export interface ChannelCfg {
  /** Detector efficiency times fibre transmittance. */
  etaTotal: number;
  /** Misalignment error probability. */
  eD: number;
  /** Dark-count / background yield per pulse. */
  Y0: number;
  eveOn: boolean;
  /** Intercept-resend probability when Eve is on. */
  eveProb: number;
}

export interface ChannelFrame {
  i: number;
  alice_bit: number;
  alice_basis: number;
  bob_basis: number;
  bob_bit: number;
  basis_match: boolean;
}

/** Knuth's multiplicative hash constant, as used in both shaders. */
const HASH = 2654435761;

/**
 * xorshift32, bit-identical to `nextu` in the WGSL and `rng` in the GLSL.
 *
 * Both shaders operate on `u32`. JS bitwise operators yield a SIGNED int32 over
 * the same 32 bits, so the per-step `>>> 0` below is for the reader's benefit --
 * it keeps each line matching its shader counterpart, and the arithmetic is
 * unchanged without it. The coercion that IS load-bearing is the last one,
 * before the value is stored and returned: drop that and the state becomes a
 * negative JS number, which `Math.fround` in `f32()` then turns into a negative
 * draw. Verified by mutation rather than assumed -- removing an intermediate
 * `>>> 0` changes nothing, removing the final one fails the PRNG test.
 */
export class Xorshift32 {
  private s: number;

  constructor(seed: number) {
    const v = seed >>> 0;
    // Both shaders guard the zero state, which is absorbing for xorshift.
    this.s = v === 0 ? 1 : v;
  }

  u32(): number {
    let x = this.s;
    x = (x ^ (x << 13)) >>> 0;
    x = (x ^ (x >>> 17)) >>> 0;
    x = (x ^ (x << 5)) >>> 0;
    this.s = x;
    return x;
  }

  /**
   * `f32(nextu(state)) / 4294967296.0`.
   *
   * `Math.fround` twice is not decoration. The shaders compute in f32: the
   * u32 -> f32 conversion rounds away the low bits of any state above 2^24,
   * and so does the division. JS would do both in f64 and land on a different
   * side of a comparison such as `< eD` often enough to desynchronise the
   * replay from the GPU.
   */
  f32(): number {
    return Math.fround(Math.fround(this.u32()) / 4294967296);
  }

  /** `select(0u, 1u, nextf(state) < 0.5)` -- note 1 when BELOW 0.5. */
  bit(): number {
    return this.f32() < 0.5 ? 1 : 0;
  }
}

/** Seed for shader invocation `id`: `seed ^ (id * HASH + 1)`, all in u32. */
function seedFor(seed: number, id: number): number {
  return ((seed >>> 0) ^ ((Math.imul(id, HASH) + 1) >>> 0)) >>> 0;
}

/**
 * One pulse, in the exact draw order both shaders use.
 *
 * Returns null when the pulse is not detected. The draw order is part of the
 * contract: a lost pulse still consumes exactly one number, and Eve's branch
 * consumes none at all when `eveProb` is zero, because the shaders
 * short-circuit `P.eveProb > 0.0 && nextf(...) < P.eveProb`. Reordering or
 * adding a draw here desynchronises the replay even if the statistics are
 * unchanged.
 */
function simulatePulse(rng: Xorshift32, cfg: ChannelCfg): Omit<ChannelFrame, "i"> | null {
  const detect = cfg.etaTotal + cfg.Y0;
  if (!(rng.f32() < detect)) return null;

  const aBit = rng.bit();
  const aBasis = rng.bit();

  let carriedBit = aBit;
  let carriedBasis = aBasis;
  const eveProb = cfg.eveOn ? cfg.eveProb : 0;
  if (eveProb > 0 && rng.f32() < eveProb) {
    const eBasis = rng.bit();
    // Eve measuring in Alice's basis learns the bit; otherwise she resends a
    // random one, which is the source of the 25% QBER she introduces.
    const eBit = eBasis === aBasis ? aBit : rng.bit();
    carriedBit = eBit;
    carriedBasis = eBasis;
  }

  const bBasis = rng.bit();
  const bBit = bBasis === carriedBasis
    ? (rng.f32() < cfg.eD ? carriedBit ^ 1 : carriedBit)
    : rng.bit();

  return {
    alice_bit: aBit, alice_basis: aBasis,
    bob_basis: bBasis, bob_bit: bBit,
    basis_match: aBasis === bBasis,
  };
}

/**
 * Replay the WebGPU round: invocation 0 runs `pulsesPerThread` pulses in a loop.
 *
 * These are the first detected pulses that invocation actually simulated, so
 * the table and the counters describe the same round.
 */
export function framesFromGpuRound(
  cfg: ChannelCfg, seed: number, pulsesPerThread: number, n: number,
): ChannelFrame[] {
  const rng = new Xorshift32(seedFor(seed, 0));
  const frames: ChannelFrame[] = [];
  for (let i = 1; i <= pulsesPerThread && frames.length < n; i++) {
    const f = simulatePulse(rng, cfg);
    if (f) frames.push({ i, ...f });
  }
  return frames;
}

/** Replay the WebGL2 round: one pulse per vertex, each with its own seed. */
export function framesFromGlRound(
  cfg: ChannelCfg, seed: number, vertexCount: number, n: number,
): ChannelFrame[] {
  const frames: ChannelFrame[] = [];
  for (let v = 0; v < vertexCount && frames.length < n; v++) {
    const f = simulatePulse(new Xorshift32(seedFor(seed, v)), cfg);
    if (f) frames.push({ i: v + 1, ...f });
  }
  return frames;
}

/**
 * Key pool, previously three identical copies of
 * `Math.max(0, Math.min(4096, pool + Math.floor(sifted * (1 - 2 * qber) * 0.25) - 64))`.
 *
 * These are illustrative demo constants, not a derived distillation bound --
 * naming them is so a reader can tell that at a glance.
 */
export const KEY_POOL_CAPACITY = 4096;
/** Fraction of sifted bits surviving error correction and privacy amplification. */
export const KEY_POOL_YIELD = 0.25;
/** Bits a notional consumer draws from the pool each round. */
export const KEY_POOL_DRAIN_PER_ROUND = 64;

export function advanceKeyPool(pool: number, sifted: number, qber: number): number {
  const distilled = Math.floor(sifted * (1 - 2 * qber) * KEY_POOL_YIELD);
  return Math.max(0, Math.min(KEY_POOL_CAPACITY, pool + distilled - KEY_POOL_DRAIN_PER_ROUND));
}
