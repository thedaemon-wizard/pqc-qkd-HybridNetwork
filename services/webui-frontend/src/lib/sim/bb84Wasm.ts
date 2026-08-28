/**
 * BB84 Monte-Carlo on WebAssembly — a fourth measured tier.
 *
 * `docs/roadmap.md` rejected WASM for this workload on bundle cost. That was a
 * reasonable prior held without a measurement. The module is now built (see
 * `wasm/bb84/src/lib.rs`) and the answer is **907 bytes**, release-profile,
 * `no_std`, no `wasm-bindgen`, no `rand`. The objection does not survive its
 * own number, so the tier ships — on exactly the terms the other accelerators
 * ship on: benchmarked against the CPU worker and adopted only on a 15 % win.
 *
 * It is not assumed to be faster. WebGPU is not, on the demo host, and says so
 * on the page. If WASM also loses, that is a result and it will say so too.
 *
 * The bytes are inlined as base64 rather than fetched. A separate `.wasm` asset
 * would be a second network round trip on a page whose whole claim is that it
 * computes client-side, and at this size the base64 overhead is ~300 bytes.
 */

/** Raw exports; see `wasm/bb84/src/lib.rs`. No allocations, no memory views. */
interface Bb84Exports {
  run_round(
    seed: number, etaTotal: number, eD: number, y0: number,
    eveOn: number, eveProb: number, pulses: number,
  ): bigint;
}

export interface WasmRoundResult {
  sifted: number;
  errors: number;
  qber: number;
}

/**
 * Decode the packed return value.
 *
 * The module returns `errors << 32 | sifted` in one u64, which reaches JS as a
 * BigInt. Packing avoids marshalling through linear memory for two integers --
 * there is no shared buffer to keep in sync and nothing to free.
 */
export function unpack(packed: bigint): WasmRoundResult {
  const sifted = Number(packed & 0xffff_ffffn);
  const errors = Number((packed >> 32n) & 0xffff_ffffn);
  return { sifted, errors, qber: sifted > 0 ? errors / sifted : 0 };
}

export class Bb84Wasm {
  private exports: Bb84Exports | null = null;

  /**
   * Instantiate. Returns false when WebAssembly is unavailable.
   *
   * `false` and a throw mean different things upstream: false is "this browser
   * cannot", a throw is "it could and did not". `bb84Sim.ts` records them as
   * different `TierTrial` outcomes, so a missing feature never renders as a
   * measured zero.
   */
  async init(bytes: Uint8Array): Promise<boolean> {
    if (typeof WebAssembly !== "object") return false;
    const { instance } = await WebAssembly.instantiate(
      bytes as unknown as BufferSource, {});
    const ex = instance.exports as unknown as Bb84Exports;
    if (typeof ex.run_round !== "function") {
      throw new Error("bb84_kernel.wasm exports no run_round");
    }
    this.exports = ex;
    return true;
  }

  /** One round, with an explicit seed so the result is reproducible. */
  runRound(seed: number, cfg: {
    etaTotal: number; eD: number; Y0: number;
    eveOn: boolean; eveProb: number; pulsesPerRound: number;
  }): WasmRoundResult {
    if (!this.exports) throw new Error("Bb84Wasm.runRound before init()");
    return unpack(this.exports.run_round(
      seed >>> 0, cfg.etaTotal, cfg.eD, cfg.Y0,
      cfg.eveOn ? 1 : 0, cfg.eveProb, cfg.pulsesPerRound));
  }
}

/**
 * The worker's PRNG, re-implemented here for the parity check only.
 *
 * The Rust kernel claims to reproduce `rnd()` in `bb84.worker.ts` bit-for-bit.
 * A claim like that needs something that can contradict it, so
 * `wasmAgreesWithWorker.test.ts` runs both over a shared seed and requires the
 * same sifted/errors counts. Without it, "ported faithfully" would be a comment.
 */
export function mulberry32(seed: number): () => number {
  let s = seed >>> 0;
  return () => {
    s |= 0; s = (s + 0x6d2b79f5) | 0;
    let t = Math.imul(s ^ (s >>> 15), 1 | s);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/** The worker's `runRound` counting loop, in isolation, for the same check. */
export function referenceRound(seed: number, cfg: {
  etaTotal: number; eD: number; Y0: number;
  eveOn: boolean; eveProb: number; pulsesPerRound: number;
}): WasmRoundResult {
  const rnd = mulberry32(seed);
  const bit = () => (rnd() < 0.5 ? 0 : 1);
  let sifted = 0, errors = 0;
  const detect = cfg.etaTotal + cfg.Y0;
  for (let i = 0; i < cfg.pulsesPerRound; i++) {
    if (rnd() >= detect) continue;
    const aBit = bit(), aBasis = bit();
    let carriedBit = aBit, carriedBasis = aBasis;
    if (cfg.eveOn && rnd() < cfg.eveProb) {
      const eBasis = bit();
      const eBit = eBasis === aBasis ? aBit : bit();
      carriedBit = eBit; carriedBasis = eBasis;
    }
    const bBasis = bit();
    const bBit = bBasis === carriedBasis
      ? (rnd() < cfg.eD ? carriedBit ^ 1 : carriedBit)
      : bit();
    if (aBasis === bBasis) {
      sifted++;
      if (aBit !== bBit) errors++;
    }
  }
  return { sifted, errors, qber: sifted > 0 ? errors / sifted : 0 };
}
