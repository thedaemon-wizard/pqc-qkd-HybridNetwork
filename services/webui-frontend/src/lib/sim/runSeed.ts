/**
 * One seed source for a simulation run, pinnable from the URL.
 *
 * `docs/roadmap.md` records the state this replaces, and the correction it
 * already carries is worth repeating because it is easy to re-assume:
 *
 *   > every rung reseeds from `Math.random()` each round -- so the rungs are
 *   > statistically equivalent, not identical, and NO RUN IS REPRODUCIBLE.
 *
 * A page whose whole claim is "here is the physics, check it yourself" cannot
 * hand a reader a figure they are unable to reproduce. `?seed=1234` makes the
 * run deterministic; without it nothing changes.
 *
 * WHAT THIS DOES NOT DO. It does not make the four accelerator tiers agree
 * with each other. The Worker runs mulberry32 and both shaders run xorshift32,
 * so the same seed gives each rung a different (still correct) sample. Making
 * them bit-identical would mean one PRNG in three languages, which is a real
 * project and not this one. What a pinned seed buys is that THE SAME RUNG,
 * given the same seed and config, replays exactly -- which is what a reader
 * checking a figure needs.
 *
 * The one place bit-exactness across implementations is already claimed and
 * needed is `Xorshift32` in `bb84Channel.ts`, which reproduces the shader PRNG
 * so the photon-frame replay shows the pulses the shader actually computed.
 * That is unaffected.
 */

/** `?seed=` as an unsigned 32-bit value, or null when absent or unparseable. */
export function seedFromLocation(search?: string): number | null {
  // Explicit parameter so this is testable without a DOM. `location` is read
  // only when nothing was passed AND a window exists -- the sims are also
  // constructed in Node by the test suite.
  const q = search
    ?? (typeof window !== "undefined" ? window.location.search : "");
  if (!q) return null;
  const raw = new URLSearchParams(q).get("seed");
  if (raw === null || raw.trim() === "") return null;
  // Accept decimal and 0x-prefixed hex. Reject anything else rather than
  // letting Number() turn "abc" into NaN and NaN into a silent 0.
  const n = /^0[xX][0-9a-fA-F]+$/.test(raw.trim())
    ? Number.parseInt(raw.trim().slice(2), 16)
    : /^\d+$/.test(raw.trim()) ? Number.parseInt(raw.trim(), 10) : NaN;
  return Number.isFinite(n) ? (n >>> 0) : null;
}

/**
 * Per-round seeds for one run.
 *
 * Pinned: seeds are a deterministic function of (base seed, round index), so
 * round 7 of `?seed=42` is the same on every machine and every reload. NOT the
 * base seed repeated -- every round would then be an identical sample and the
 * QBER history would be a flat line that looks like a stuck sensor.
 *
 * Unpinned: `Math.random()`, exactly as before. The default path is unchanged,
 * which matters because the demo's headline figures were measured on it.
 */
export class RunSeeds {
  private readonly base: number | null;
  private round = 0;

  constructor(base: number | null) { this.base = base; }

  static fromLocation(search?: string): RunSeeds {
    return new RunSeeds(seedFromLocation(search));
  }

  /** True when the run is reproducible, for the UI to say so. */
  get pinned(): boolean { return this.base !== null; }

  /** The base seed, for display and for export provenance. */
  get value(): number | null { return this.base; }

  /** Next per-round seed. Advances the counter whether pinned or not, so the
   *  round index means the same thing in both modes. */
  next(): number {
    const i = this.round++;
    if (this.base === null) return (Math.random() * 0xffffffff) >>> 0;
    // splitmix32 finalizer on (base + index). A plain `base + i` would hand
    // consecutive rounds adjacent seeds, and both mulberry32 and xorshift32
    // correlate visibly on those -- the first outputs of seed 41 and 42 are
    // close, which would show up as structure in the QBER history that the
    // physics did not put there.
    let x = (this.base + i * 0x9e3779b9) >>> 0;
    x = Math.imul(x ^ (x >>> 16), 0x21f0aaad) >>> 0;
    x = Math.imul(x ^ (x >>> 15), 0x735a2d97) >>> 0;
    return (x ^ (x >>> 15)) >>> 0;
  }

  /** Restart the round counter, so re-running a pinned seed replays it. */
  reset(): void { this.round = 0; }
}
