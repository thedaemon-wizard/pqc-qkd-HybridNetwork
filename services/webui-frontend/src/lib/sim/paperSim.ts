/**
 * Client-side Paper Data Exchange orchestrator (Round 5) — TS port of
 * the former services/webui-backend/app/paper_flow.py (deleted; this is now the
 * only implementation). Reproduces the 5-phase multi-hop
 * flow, arXiv:2604.05599 Table-III packet budgets, the layer-aware failure
 * cascade (Round 4 fix), and the per-cycle ChaCha20-Poly1305 data payload — all in the
 * browser. Emits the same PaperFlowState shape the page already renders.
 */
import { chachaSeal, deriveHkdfSha3, encodeUtf8, randomBytes, toHex } from "./crypto";

export type Layer = "qkd" | "arnika" | "wireguard" | "rosenpass" | "data";

export interface PhaseBudget {
  phase: number; name: string; packets: number; bytes: number;
  period_s: number | null; grace_s: number; description: string;
}
export interface CascadeEvent {
  t_offset_s: number; layer: string; description: string;
  triggered_at: number | null; fired: boolean;
}

const PHASE_BUDGETS: Record<number, Omit<PhaseBudget, "phase">> = {
  1: { name: "Quantum Plane", packets: 0, bytes: 0, period_s: null, grace_s: 0,
       description: "QKD device generates symmetric key material; no IP-layer traffic in this phase." },
  2: { name: "Arnika QKD key_ID exchange", packets: 2, bytes: 78, period_s: 120, grace_s: 180,
       description: "Arnika fetches QKD key from local ETSI 014 KME and negotiates the active key_ID with the neighbour Arnika." },
  3: { name: "WireGuard hop handshake", packets: 3, bytes: 398, period_s: 120, grace_s: 60,
       description: "Curve25519 + ChaCha20 handshake establishes the QKD-secured hop tunnel; the QKD-derived WireGuard preshared key is mixed into the Noise_IKpsk2 chaining key, so it contributes to the transport keys." },
  4: { name: "Rosenpass PQC handshake", packets: 4, bytes: 4772, period_s: 120, grace_s: 180,
       description: "Classic McEliece + Kyber end-to-end PQC handshake carried over the chain of QKD-secured WireGuard hops." },
  5: { name: "Final data tunnel + Data Exchange", packets: 0, bytes: 0, period_s: 120, grace_s: 60,
       description: "Application data tunnel (WireGuard with ChaCha20-Poly1305) uses a WireGuard preshared key derived from the Rosenpass output. Not an IKEv2 PSK -- see docs/vici-ppk.md." },
};
/**
 * Mean end-to-end setup time, arXiv:2604.05599 Evaluation, Test 2 - Long Distance.
 *
 * These are LITERATURE values and they already have an owner:
 * `services/webui-backend/app/paper_budgets.py`, pinned by
 * `tests/test_paper_budgets.py`. They were restated here as bare literals with
 * nothing comparing the two, which is the drift shape this project has spent a
 * lot of effort removing elsewhere -- one number, two homes, no test.
 *
 * `tests/test_paper_constants_agree_across_ports.py` now fails if these and the
 * Python module disagree. Change both, or neither.
 */
export const MEAN_10_HOP_SETUP_S = 10.27;
export const MEAN_100_HOP_SETUP_S = 10.62;

const CASCADE_STAGES: [number, Layer, string][] = [
  [0, "qkd", "QKD plane outage injected"],
  [180, "arnika", "Arnika fails over to random key"],
  [240, "wireguard", "WireGuard hop tunnel grace expires"],
  [360, "rosenpass", "Rosenpass handshake blocked"],
  [420, "rosenpass", "Rosenpass falls over to random PSK"],
  [540, "data", "Final data tunnel handshake fails (early cascade)"],
  [720, "data", "Full data-path interruption (worst case)"],
];
const TOTAL_PACKETS = Object.values(PHASE_BUDGETS).reduce((a, p) => a + p.packets, 0);
const TOTAL_BYTES = Object.values(PHASE_BUDGETS).reduce((a, p) => a + p.bytes, 0);
const PHASE_FAIL: Record<Layer, number> = { qkd: 1, arnika: 2, wireguard: 3, rosenpass: 4, data: 5 };
/**
 * Dwell per phase, chosen so the swimlane is watchable.
 *
 * Exported for the same reason as e2eSim's, and it is a DIFFERENT value (350
 * here, 450 there) -- which is exactly why the CSV must carry the page's own
 * nominal rather than a shared constant. The measured column is wall-clock and
 * Chrome clamps timers to roughly 1 Hz in a hidden tab, so a background
 * recording inflates it; publishing the nominal beside it makes that visible.
 *
 * Note this is UI dwell only. It has no relation to the paper's 240-720 s
 * cascade offsets, which are simulated time and come from the "Fail-Safe
 * Mechanism" subsection of Implementation -- not from Table 1, which gives
 * packet and byte budgets.
 */
export const NOMINAL_PHASE_DWELL_MS = 350;

interface CascadeSched { t_offset_s: number; layer: Layer; description: string; triggered_at: number; }

export interface PaperFlowState {
  status: "idle" | "running" | "paused";
  current_phase: number; current_phase_name: string;
  hop_count: number; dual_path: boolean;
  cycles_total: number; cycles_succeeded: number;
  packets_total: number; bytes_total: number;
  last_data_payload_b64: string;
  failure: { active_layer: Layer | null; started_at: number | null; cascade: CascadeEvent[] };
  history: { phase: number; name: string; started_at: number; completed_at: number | null;
             packets: number; bytes: number; detail: Record<string, unknown> }[];
  paper_budgets: { phases: PhaseBudget[]; total_handshake_packets: number;
                   total_handshake_bytes: number; mean_10_hop_setup_s: number;
                   mean_100_hop_setup_s: number };
  engine?: string;
}

function b64(bytes: Uint8Array): string {
  let s = ""; for (const b of bytes) s += String.fromCharCode(b);
  return btoa(s);
}

export class PaperSim {
  private status: "idle" | "running" | "paused" = "idle";
  private phase = 0;
  private hop = 4;
  private dual = false;
  private cyclesTotal = 0; private cyclesSucceeded = 0;
  private packetsTotal = 0; private bytesTotal = 0;
  private lastPayload = "";
  // Key material for the phase-5 AEAD, produced by phases 2 and 4.
  private qkdKey: Uint8Array | null = null;
  private pqcSecret: Uint8Array | null = null;
  private failLayer: Layer | null = null;
  private failStarted: number | null = null;
  private cascade: CascadeSched[] = [];
  private history: PaperFlowState["history"] = [];
  private cycleAccepted = true;
  private timer: number | null = null;
  private phaseStart = 0;
  private onState: (s: PaperFlowState) => void;

  constructor(onState: (s: PaperFlowState) => void) { this.onState = onState; this.emit(); }

  private budgets(): PhaseBudget[] {
    return Object.entries(PHASE_BUDGETS).map(([p, info]) => ({ phase: +p, ...info }));
  }

  snapshot(): PaperFlowState {
    const now = Date.now() / 1000;
    return {
      status: this.status, current_phase: this.phase,
      current_phase_name: PHASE_BUDGETS[this.phase]?.name ?? "idle",
      hop_count: this.hop, dual_path: this.dual,
      cycles_total: this.cyclesTotal, cycles_succeeded: this.cyclesSucceeded,
      packets_total: this.packetsTotal, bytes_total: this.bytesTotal,
      last_data_payload_b64: this.lastPayload,
      failure: {
        active_layer: this.failLayer, started_at: this.failStarted,
        cascade: this.cascade.map((c) => ({
          t_offset_s: c.t_offset_s, layer: c.layer, description: c.description,
          triggered_at: c.triggered_at, fired: now >= c.triggered_at,
        })),
      },
      history: this.history.slice(-30),
      paper_budgets: {
        phases: this.budgets(), total_handshake_packets: TOTAL_PACKETS,
        total_handshake_bytes: TOTAL_BYTES,
        mean_10_hop_setup_s: MEAN_10_HOP_SETUP_S,
        mean_100_hop_setup_s: MEAN_100_HOP_SETUP_S,
      },
      engine: "client-side (JS)",
    };
  }
  private emit() { this.onState(this.snapshot()); }

  start() { this.status = "running"; if (this.phase === 0) this.beginCycle(); this.ensureLoop(); this.emit(); }
  pause() {
    this.status = "paused";
    // Stop the timer, matching E2ESim.pause(). Leaving it running only for
    // tick() to early-return kept waking the main thread 10x a second on a
    // paused page, which on a public demo is a battery cost for nothing.
    this.stopLoop();
    this.emit();
  }
  resume() { this.status = "running"; this.ensureLoop(); this.emit(); }

  /**
   * Advance exactly one phase without starting the timer.
   *
   * Refuses while running, unlike E2ESim.step(), which ignores status and so
   * advances a paused run while leaving the badge reading "paused". Stepping a
   * simulation that is already advancing on its own is not a meaningful
   * request, and silently honouring it makes the phase counter disagree with
   * what the user sees.
   */
  step() {
    if (this.status === "running") return;
    if (this.phase === 0) { this.beginCycle(); this.emit(); return; }
    this.runPhase();
  }
  reset() {
    this.status = "idle"; this.phase = 0;
    this.cyclesTotal = this.cyclesSucceeded = this.packetsTotal = this.bytesTotal = 0;
    this.lastPayload = ""; this.failLayer = null; this.failStarted = null;
    this.qkdKey = null; this.pqcSecret = null;
    this.cascade = []; this.history = []; this.cycleAccepted = true; this.emit();
  }
  setHopCount(n: number) { this.hop = Math.max(1, Math.min(8, Math.round(n))); this.emit(); }
  setDualPath(on: boolean) { this.dual = on; this.emit(); }

  injectFailure(layer: Layer) {
    const now = Date.now() / 1000;
    const startIdx = Math.max(0, CASCADE_STAGES.findIndex((s) => s[1] === layer));
    const baseT = CASCADE_STAGES[startIdx][0];
    this.failLayer = layer; this.failStarted = now;
    this.cascade = CASCADE_STAGES.slice(startIdx).map(([t, l, d]) => ({
      t_offset_s: t - baseT, layer: l, description: d, triggered_at: now + (t - baseT),
    }));
    this.emit();
  }
  clearFailure() { this.failLayer = null; this.failStarted = null; this.cascade = []; this.emit(); }

  /** Stop the tick timer. Idempotent. */
  private stopLoop() {
    if (this.timer !== null) { clearInterval(this.timer); this.timer = null; }
  }

  dispose() { this.stopLoop(); }

  private ensureLoop() {
    if (this.timer !== null) return;
    this.phaseStart = performance.now();
    this.timer = window.setInterval(() => this.tick(), 100);
  }
  private beginCycle() { this.cyclesTotal += 1; this.cycleAccepted = true; this.enterPhase(1); }

  private tick() {
    if (this.status !== "running") return;
    if (performance.now() - this.phaseStart >= NOMINAL_PHASE_DWELL_MS) this.runPhase();
  }

  private enterPhase(phase: number) {
    this.phase = phase;
    this.history.push({ phase, name: PHASE_BUDGETS[phase].name,
      started_at: Date.now() / 1000, completed_at: null, packets: 0, bytes: 0, detail: {} });
    if (this.history.length > 30) this.history = this.history.slice(-30);
    this.phaseStart = performance.now();
  }

  private runPhase() {
    const phase = this.phase;
    const info = PHASE_BUDGETS[phase];
    let pkts = info.packets, bytes = info.bytes;
    const failedThisPhase = this.failLayer !== null && PHASE_FAIL[this.failLayer] === phase;
    if (failedThisPhase) this.cycleAccepted = false;
    const detail: Record<string, unknown> = {
      period_s: info.period_s, grace_s: info.grace_s, failed: failedThisPhase };

    // Phase 2 yields the QKD key, phase 4 the PQC secret. Both are generated
    // where the modelled flow produces them so phase 5 cannot silently run on
    // material that was never established -- if a cascade failure skipped the
    // producing phase, the seal below has nothing to work with and says so.
    if (phase === 2 && !failedThisPhase) this.qkdKey = randomBytes(32);
    if (phase === 4 && !failedThisPhase) this.pqcSecret = randomBytes(32);

    if (phase === 5 && !failedThisPhase) {
      // PHASE_BUDGETS[5] describes this as "WireGuard with ChaCha20-Poly1305
      // ... a PSK derived from the Rosenpass output", and the page titles the
      // panel accordingly. Previously the payload was plain randomBytes(64) and
      // no AEAD ran at all, so the label asserted a cryptographic property the
      // code did not provide. Do what the description says.
      if (this.qkdKey && this.pqcSecret) {
        const psk = deriveHkdfSha3(this.qkdKey, this.pqcSecret, "paper-flow");
        const plaintext = encodeUtf8(
          `PAPER-FLOW cycle ${this.cyclesTotal + 1} hops=${this.hop} Alice->Bob`);
        const { ciphertext, nonce } = chachaSeal(psk, plaintext);
        pkts = 1;
        // On the wire the nonce travels with the ciphertext, so both count.
        bytes = ciphertext.length + nonce.length;
        this.lastPayload = b64(ciphertext);
        detail.data_bytes = bytes;
        detail.aead = "ChaCha20-Poly1305";
        detail.psk_prefix = toHex(psk).slice(0, 16);
      } else {
        // Reached only if an upstream phase failed without tripping
        // failedThisPhase. Surface it rather than emitting a decorative blob.
        pkts = 0; bytes = 0; this.lastPayload = "";
        detail.data_bytes = 0;
        detail.error = "no PSK: QKD or PQC material missing";
      }
    }
    this.packetsTotal += pkts; this.bytesTotal += bytes;
    // close the open history record
    for (let i = this.history.length - 1; i >= 0; i--) {
      if (this.history[i].phase === phase && this.history[i].completed_at === null) {
        this.history[i].completed_at = Date.now() / 1000;
        this.history[i].packets = pkts; this.history[i].bytes = bytes;
        this.history[i].detail = detail; break;
      }
    }

    if (failedThisPhase || phase >= 5) {
      if (this.cycleAccepted) this.cyclesSucceeded += 1;
      this.phase = 0;
      if (this.status === "running") this.beginCycle();   // next cycle
    } else {
      this.enterPhase(phase + 1);
    }
    this.emit();
  }
}
