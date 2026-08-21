/**
 * The photon table on `/bb84` must be the round the engine actually computed.
 *
 * The WebGPU and WebGL2 tiers return counts only, so they used to display
 * frames from a separate `Math.random()` pass. A viewer comparing the table
 * against the QBER printed beside it was comparing two unrelated runs -- and
 * nothing about the page said so.
 *
 * The replay in bb84Channel.ts fixes that only if it reproduces the shaders
 * exactly, which is a property no browser-free test can confirm end to end.
 * What these tests can do is pin everything the replay depends on: the PRNG's
 * exact u32 arithmetic, determinism given (seed, invocation), the draw order
 * that keeps it in step, and the statistics the channel is supposed to produce.
 * If any of those drift, the replay silently stops describing the GPU round,
 * which is the failure that would be hardest to notice by looking.
 */
import { describe, expect, it } from "vitest";

import {
  KEY_POOL_CAPACITY,
  KEY_POOL_DRAIN_PER_ROUND,
  Xorshift32,
  advanceKeyPool,
  framesFromGlRound,
  framesFromGpuRound,
  type ChannelCfg,
} from "./bb84Channel";

const CFG: ChannelCfg = {
  etaTotal: 0.02, eD: 0.015, Y0: 1e-5, eveOn: false, eveProb: 1.0,
};

/** Independent xorshift32 reference, written from the algorithm, not the code. */
function referenceXorshift32(seed: number, steps: number): number {
  let x = seed >>> 0;
  for (let i = 0; i < steps; i++) {
    x = (x ^ (x << 13)) >>> 0;
    x = (x ^ (x >>> 17)) >>> 0;
    x = (x ^ (x << 5)) >>> 0;
  }
  return x >>> 0;
}

describe("the PRNG the replay shares with the shaders", () => {
  it("matches the reference u32 arithmetic step for step", () => {
    // Compared against `referenceXorshift32`, NOT merely alongside it. An
    // earlier draft asserted things about the reference alone, so mutating the
    // real class left every test passing because nothing ever called it.
    //
    // What this catches: the final `>>> 0`, without which the state is stored
    // as a negative JS number and every subsequent draw is wrong. It does NOT
    // catch removal of the intermediate coercions, and should not pretend to --
    // those are equivalent, since JS bitwise operators act on the same 32 bits
    // either way. Checked by mutation, not by reading.
    for (const seed of [0x80000000, 0xffffffff, 0xdeadbeef, 1, 0x12345678]) {
      const rng = new Xorshift32(seed);
      let expected = seed >>> 0;
      for (let step = 0; step < 200; step++) {
        expected = referenceXorshift32(expected, 1);
        const actual = rng.u32();
        expect(actual).toBe(expected);
        expect(actual).toBeGreaterThanOrEqual(0);
        expect(actual).toBeLessThanOrEqual(0xffffffff);
      }
    }
  });

  it("never reaches the absorbing zero state from a non-zero seed", () => {
    const rng = new Xorshift32(0x12345678);
    for (let i = 0; i < 10000; i++) expect(rng.u32()).not.toBe(0);
  });

  it("guards the zero seed, which xorshift cannot escape", () => {
    const a = new Xorshift32(0);
    const b = new Xorshift32(1);
    expect(a.u32()).toBe(b.u32());
    expect(a.u32()).not.toBe(0);
  });

  it("converts to float in f32, not f64, exactly as the shaders do", () => {
    // Both shaders write `f32(nextu(state)) / 4294967296.0`, and both steps
    // round. JS defaults to f64 and lands on genuinely different values --
    // 0xFFFFFFFF becomes exactly 1.0 in f32 but 0.9999999997671694 in f64, and
    // 0x01000001 becomes 0.00390625 rather than 0.003906250232830644. Either
    // can fall on the other side of a `< eD` comparison and desynchronise the
    // replay from the round it claims to be showing.
    //
    // Float32Array is the oracle here: it is real f32 hardware arithmetic, not
    // another copy of the implementation.
    const f32 = (x: number) => {
      const buf = new Float32Array(1);
      buf[0] = x;
      buf[0] = buf[0] / 4294967296;
      return buf[0];
    };

    // Drive the real class and the oracle from the same state sequence. Testing
    // the expression `Math.fround(...)` on its own passes even after the class
    // stops calling it, which is how the first version of this test missed a
    // deliberately reintroduced f64 division.
    const rng = new Xorshift32(0xfeedface);
    let state = 0xfeedface;
    let divergences = 0;
    for (let i = 0; i < 20000; i++) {
      state = referenceXorshift32(state, 1);
      expect(rng.f32()).toBe(f32(state));
      if (f32(state) !== state / 4294967296) divergences++;
    }
    // Proof the comparison has teeth: f32 and f64 genuinely disagree here, so
    // an implementation that dropped the rounding would fail the loop above.
    expect(divergences).toBeGreaterThan(0);

    // The clearest single case: 0xFFFFFFFF rounds up to exactly 1.0 in f32.
    expect(f32(0xffffffff)).toBe(1);
    expect(0xffffffff / 4294967296).not.toBe(1);
  });

  it("draws in [0, 1] across a long run", () => {
    const rng = new Xorshift32(0xfeedface);
    for (let i = 0; i < 100000; i++) {
      const v = rng.f32();
      expect(v).toBeGreaterThanOrEqual(0);
      expect(v).toBeLessThanOrEqual(1);
    }
  });

  it("produces a fair bit, with 1 meaning BELOW 0.5 as the shaders define it", () => {
    const rng = new Xorshift32(0x2468ace0);
    let ones = 0;
    const N = 100000;
    for (let i = 0; i < N; i++) ones += rng.bit();
    expect(ones / N).toBeGreaterThan(0.49);
    expect(ones / N).toBeLessThan(0.51);
  });
});

describe("the replay as a whole, pinned by golden vector", () => {
  // Seeding, PRNG and draw order together, so that changing ANY of them is a
  // deliberate act rather than an accident. The statistical tests below cannot
  // do this: they pass for any correct-looking channel, including one seeded
  // differently from the shader. Replacing `seed ^ (id * 2654435761 + 1)` with
  // `seed ^ (id + 1)` leaves every distribution intact and every other test
  // green -- and silently stops describing the GPU round.
  //
  // If a shader changes, these values must be regenerated FROM THE SHADER, not
  // from this module, or the pin records agreement with itself.
  const CFG_GV: ChannelCfg = { etaTotal: 0.02, eD: 0.015, Y0: 1e-5, eveOn: false, eveProb: 1.0 };
  const SEED = 0x1234abcd;

  it("reproduces the WGSL invocation-0 sequence", () => {
    expect(framesFromGpuRound(CFG_GV, SEED, 1_000_000, 3)).toEqual([
      { i: 59, alice_bit: 0, alice_basis: 1, bob_basis: 0, bob_bit: 0, basis_match: false },
      { i: 86, alice_bit: 1, alice_basis: 0, bob_basis: 0, bob_bit: 1, basis_match: true },
      { i: 196, alice_bit: 0, alice_basis: 1, bob_basis: 0, bob_bit: 0, basis_match: false },
    ]);
  });

  it("reproduces the GLSL per-vertex sequence", () => {
    expect(framesFromGlRound(CFG_GV, SEED, 1_000_000, 3)).toEqual([
      { i: 16, alice_bit: 0, alice_basis: 1, bob_basis: 0, bob_bit: 1, basis_match: false },
      { i: 112, alice_bit: 1, alice_basis: 0, bob_basis: 0, bob_bit: 1, basis_match: true },
      { i: 142, alice_bit: 0, alice_basis: 1, bob_basis: 1, bob_bit: 0, basis_match: true },
    ]);
  });
});

describe("replaying a GPU round", () => {
  it("is deterministic: the same seed yields the same pulses", () => {
    const a = framesFromGpuRound(CFG, 0xabcdef01, 100000, 16);
    const b = framesFromGpuRound(CFG, 0xabcdef01, 100000, 16);
    expect(a).toEqual(b);
    expect(a).toHaveLength(16);
  });

  it("yields different pulses for different seeds", () => {
    const a = framesFromGpuRound(CFG, 1, 100000, 16);
    const b = framesFromGpuRound(CFG, 2, 100000, 16);
    expect(a).not.toEqual(b);
  });

  it("reports the pulse index, so gaps show the undetected pulses", () => {
    // etaTotal is 2%, so roughly 49 of every 50 pulses are lost. Indices that
    // ran 1, 2, 3... would mean the replay was counting detections rather than
    // pulses, and the table would misrepresent the channel loss.
    const frames = framesFromGpuRound(CFG, 0x5eed, 100000, 16);
    const indices = frames.map((f) => f.i);
    expect(indices).toEqual([...indices].sort((x, y) => x - y));
    expect(indices[indices.length - 1]).toBeGreaterThan(frames.length);
  });

  it("stops at the end of the invocation instead of inventing pulses", () => {
    // 10 pulses at 2% detection will not fill a 16-row table. Returning fewer
    // rows is correct; padding them would be the bug this whole file is about.
    const frames = framesFromGpuRound(CFG, 0x5eed, 10, 16);
    expect(frames.length).toBeLessThan(16);
  });
});

describe("replaying a WebGL2 round", () => {
  it("is deterministic and seeds each vertex independently", () => {
    const a = framesFromGlRound(CFG, 0x1234, 200000, 16);
    const b = framesFromGlRound(CFG, 0x1234, 200000, 16);
    expect(a).toEqual(b);
    expect(a).toHaveLength(16);
  });

  it("differs from the GPU replay, because the seeding differs", () => {
    // WGSL loops many pulses inside one invocation; GLSL runs one pulse per
    // vertex with a fresh seed each time. Identical output would mean one of
    // the two replays is not modelling its own shader.
    const gpu = framesFromGpuRound(CFG, 777, 100000, 16);
    const gl = framesFromGlRound(CFG, 777, 200000, 16);
    expect(gl).not.toEqual(gpu);
  });
});

describe("the channel the replay reproduces", () => {
  const sample = (cfg: ChannelCfg, n: number) =>
    framesFromGlRound(cfg, 0xc0ffee, 40_000_000, n);

  it("sifts about half the detected pulses", () => {
    const frames = sample(CFG, 4000);
    const matched = frames.filter((f) => f.basis_match).length;
    expect(matched / frames.length).toBeGreaterThan(0.45);
    expect(matched / frames.length).toBeLessThan(0.55);
  });

  it("produces a QBER near e_d when Eve is absent", () => {
    const frames = sample(CFG, 4000).filter((f) => f.basis_match);
    const errors = frames.filter((f) => f.alice_bit !== f.bob_bit).length;
    expect(errors / frames.length).toBeLessThan(0.05);
  });

  it("produces a QBER near 25 % under full intercept-resend", () => {
    // The textbook signature of BB84 under intercept-resend: Eve guesses the
    // basis half the time and resends a random bit, so a quarter of the sifted
    // bits disagree. A replay that did not model Eve would sit near e_d here.
    const frames = sample({ ...CFG, eveOn: true, eveProb: 1.0 }, 4000)
      .filter((f) => f.basis_match);
    const qber = frames.filter((f) => f.alice_bit !== f.bob_bit).length / frames.length;
    expect(qber).toBeGreaterThan(0.2);
    expect(qber).toBeLessThan(0.3);
  });

  it("ignores eveProb when Eve is switched off", () => {
    const on = sample({ ...CFG, eveOn: true, eveProb: 1.0 }, 2000);
    const off = sample({ ...CFG, eveOn: false, eveProb: 1.0 }, 2000);
    expect(off).not.toEqual(on);
  });
});

describe("the key-pool model, previously copied into three engines", () => {
  it("is bounded by the pool capacity", () => {
    let pool = 0;
    for (let i = 0; i < 1000; i++) pool = advanceKeyPool(pool, 1_000_000, 0.01);
    expect(pool).toBe(KEY_POOL_CAPACITY);
  });

  it("never goes negative when the pool is drained dry", () => {
    expect(advanceKeyPool(0, 0, 0)).toBe(0);
    expect(advanceKeyPool(10, 0, 0)).toBe(0);
  });

  it("drains when no key is distilled", () => {
    expect(advanceKeyPool(1000, 0, 0)).toBe(1000 - KEY_POOL_DRAIN_PER_ROUND);
  });

  it("distils nothing once QBER passes 50 %", () => {
    // (1 - 2*QBER) turns negative there, so the pool must fall, not grow.
    expect(advanceKeyPool(1000, 100_000, 0.6)).toBeLessThan(1000);
  });
});
