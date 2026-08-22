/// <reference lib="webworker" />
/**
 * BB84 Monte-Carlo Web Worker (Round 5) — runs the heavy per-pulse simulation
 * OFF the main thread so the UI never blocks (parallel processing per user).
 *
 * Model per pulse: Alice random bit+basis → channel transmittance η_total →
 * optional Eve intercept-resend (prob p, random basis) → Bob random basis +
 * measurement → sift (Alice basis == Bob basis) → QBER (misalignment e_d + dark
 * counts). Mirrors the discrete-variable BB84 the backend simulates, using the
 * closed-form channel params (η_total, Y0, e_d) from keyrate.ts.
 *
 * Unlike the GPU tiers this loop records its frames inline as it runs, so the
 * photon table is the run by construction. The key-pool model is shared with
 * them via bb84Channel.ts, where it used to be a third verbatim copy.
 */
import { advanceKeyPool } from "./bb84Channel";
import { bundledChannel } from "./keyrate";

interface Cfg {
  etaTotal: number; eD: number; Y0: number;
  eveOn: boolean; eveProb: number; pulsesPerRound: number;
}
interface Frame {
  i: number; alice_bit: number; alice_basis: number;
  bob_basis: number; bob_bit: number; basis_match: boolean;
}

// The worker starts before /api/sim/params can arrive, so whatever is here is
// what the first rounds are computed from. It was a hardcoded channel unrelated
// to the configured one; it is now the same bundled set the page falls back to.
let cfg: Cfg = {
  ...bundledChannel(),
  eveOn: false, eveProb: 1.0, pulsesPerRound: 1_000_000,
};
let running = false;
let pool = 0;
let timer: ReturnType<typeof setInterval> | null = null;

// Fast seedable PRNG (mulberry32) — far faster than Math.random in tight loops.
let rngState = (Date.now() ^ 0x9e3779b9) >>> 0;
function rnd(): number {
  rngState |= 0; rngState = (rngState + 0x6d2b79f5) | 0;
  let t = Math.imul(rngState ^ (rngState >>> 15), 1 | rngState);
  t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
  return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
}
const bit = () => (rnd() < 0.5 ? 0 : 1);

function runRound(): { qber: number; pool_size: number; frames: Frame[]; pulses: number } {
  const { etaTotal, eD, Y0, eveOn, eveProb, pulsesPerRound } = cfg;
  let sifted = 0, errors = 0;
  const frames: Frame[] = [];
  const detect = etaTotal + Y0;                       // detection prob incl. dark counts
  for (let i = 0; i < pulsesPerRound; i++) {
    if (rnd() >= detect) continue;                    // photon lost / no click
    const aBit = bit(), aBasis = bit();
    let carriedBit = aBit, carriedBasis = aBasis;
    if (eveOn && rnd() < eveProb) {                   // Eve intercept-resend
      const eBasis = bit();
      const eBit = eBasis === aBasis ? aBit : bit();  // wrong basis → random
      carriedBit = eBit; carriedBasis = eBasis;
    }
    const bBasis = bit();
    let bBit: number;
    if (bBasis === carriedBasis) {
      bBit = rnd() < eD ? carriedBit ^ 1 : carriedBit; // misalignment error
    } else {
      bBit = bit();                                   // basis mismatch → random
    }
    const match = aBasis === bBasis;                  // sift on Alice/Bob bases
    if (match) {
      sifted++;
      if (aBit !== bBit) errors++;
    }
    if (frames.length < 16) {
      frames.push({ i, alice_bit: aBit, alice_basis: aBasis,
        bob_basis: bBasis, bob_bit: bBit, basis_match: match });
    }
  }
  const qber = sifted > 0 ? errors / sifted : 0;
    pool = advanceKeyPool(pool, sifted, qber);
  return { qber, pool_size: pool, frames, pulses: pulsesPerRound };
}

function loop() {
  if (!running) return;
  const t0 = performance.now();
  const r = runRound();
  const dt = Math.max(performance.now() - t0, 1e-3);
  (self as DedicatedWorkerGlobalScope).postMessage({
    type: "frames", qber: r.qber, pool_size: r.pool_size, frames: r.frames,
    pulsesPerSec: Math.round(r.pulses / (dt / 1000)), engine: "Worker (CPU)",
  });
}

self.onmessage = (ev: MessageEvent) => {
  const m = ev.data;
  if (m.type === "config") { cfg = { ...cfg, ...m.params }; }
  else if (m.type === "start") {
    running = true;
    if (timer === null) timer = setInterval(loop, 250);
  } else if (m.type === "stop") {
    running = false;
    if (timer !== null) { clearInterval(timer); timer = null; }
  }
};
