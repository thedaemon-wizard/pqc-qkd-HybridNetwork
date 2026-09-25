/**
 * Client-side Paper Data Exchange orchestrator (Round 5) — TS port of
 * the former services/webui-backend/app/paper_flow.py (deleted; this is now the
 * only implementation). Reproduces the 5-phase multi-hop
 * flow, arXiv:2604.05599 Table 1 packet budgets, the layer-aware failure
 * cascade (Round 4 fix), and the per-cycle ChaCha20-Poly1305 data payload — all in the
 * browser. Emits the same PaperFlowState shape the page already renders.
 */
import { chachaSeal, deriveHkdfSha3, encodeUtf8, randomBytes, toHex } from "./crypto";
import { dwellDone, dwellMs, LOOP_TICK_MS } from "./pacing";

export type Layer = "qkd" | "arnika" | "wireguard" | "rosenpass" | "data";

export interface PhaseBudget {
  phase: number; name: string; packets: number; bytes: number;
  period_s: number | null; grace_s: number; description: string;
}
export interface CascadeEvent {
  t_offset_s: number; layer: string; description: string;
  triggered_at: number | null; fired: boolean;
}

/**
 * Table 1 per phase, mirrored from services/webui-backend/app/paper_budgets.py
 * (tests/test_paper_constants_agree_across_ports.py compares the two).
 *
 * `grace_s` is the paper's grace WINDOW: 4.3 Fail-Safe Mechanism gives 60 s
 * for WireGuard, Arnika and Rosenpass alike ("every 120s, with a 60s grace
 * window"). Arnika and Rosenpass used to read 180 here, which is period + grace
 * -- the time until a missed refresh bites -- in a field named for the window.
 */
const PHASE_BUDGETS: Record<number, Omit<PhaseBudget, "phase">> = {
  1: { name: "Quantum Plane", packets: 0, bytes: 0, period_s: null, grace_s: 0,
       description: "QKD device generates symmetric key material; no IP-layer traffic in this phase." },
  2: { name: "Arnika QKD key_ID exchange", packets: 2, bytes: 78, period_s: 120, grace_s: 60,
       description: "Arnika fetches QKD key from local ETSI 014 KME and negotiates the active key_ID with the neighbour Arnika." },
  3: { name: "WireGuard hop handshake", packets: 3, bytes: 398, period_s: 120, grace_s: 60,
       description: "Curve25519 + ChaCha20 handshake establishes the QKD-secured hop tunnel; the QKD-derived WireGuard preshared key is mixed into the Noise_IKpsk2 chaining key, so it contributes to the transport keys." },
  4: { name: "Rosenpass PQC handshake", packets: 4, bytes: 4772, period_s: 120, grace_s: 60,
       description: "Classic McEliece + Kyber end-to-end PQC handshake carried over the chain of QKD-secured WireGuard hops." },
  5: { name: "Final data tunnel + Data Exchange", packets: 0, bytes: 0, period_s: 120, grace_s: 60,
       description: "Application data tunnel (WireGuard with ChaCha20-Poly1305) uses a WireGuard preshared key derived from the Rosenpass output alone; the QKD keys stay on the hops. Not an IKEv2 PSK -- see docs/vici-ppk.md." },
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

/**
 * The cascade after a QKD outage, as arXiv:2604.05599 Test 5 (Simulated QKD
 * malfunction) walks it, plus the 720 s upper bound from 4.3 Fail-Safe
 * Mechanism. The 240 s stage used to read "grace expires" and the 540 s stage
 * "handshake fails": in the paper the hop tries a new key and fails at 240 s,
 * its grace passes at 300 s, the data tunnel's handshake fails at 480 s and
 * the tunnel is disrupted after 540 s.
 */
const CASCADE_STAGES: [number, Layer, string][] = [
  [0, "qkd", "QKD plane outage injected"],
  [180, "arnika", "Arnika fails over to random key"],
  [240, "wireguard", "WireGuard hop tries a new session key and fails"],
  [300, "wireguard", "WireGuard hop grace period passes; no further PQC handshakes"],
  [360, "rosenpass", "Rosenpass handshake blocked"],
  [420, "rosenpass", "Rosenpass falls over to random PSK"],
  [480, "data", "Final data tunnel handshake fails"],
  [540, "data", "Final data tunnel disrupted"],
  [720, "data", "Full data-path interruption (worst case, 4.3 upper bound)"],
];
// Abbreviations for the 187px legend column. Keyed by the same phase numbers
// as PHASE_BUDGETS, and asserted against it by
// src/lib/sim/phaseNamesAgree.test.ts so a phase cannot gain a name here and
// keep a different one there.
const PHASE_SHORT_NAMES: Record<number, string> = {
  1: "Quantum Plane",
  2: "QKD key_ID exchange",
  3: "WireGuard hop",
  4: "Rosenpass PQC",
  5: "Data tunnel",
};

/**
 * Phase numbers and names, for anything that needs to LABEL a phase without
 * driving one.
 *
 * `MultiHopTopologySvg` used to carry its own copy of the labels, and it had
 * copied them from the WRONG page: the four `/e2e` phase names, verbatim from
 * `QuantumSecureE2E.tsx`, pasted into a figure driven by this five-phase
 * counter. At phase 3 the legend read "PQC Handshake" while the inspector --
 * reading `PHASE_BUDGETS` -- said "WireGuard hop handshake"; at phase 4 the
 * figure drew the end-to-end data tunnel while the inspector said "Rosenpass
 * PQC handshake"; and at phase 5 nothing lit at all, because the legend had
 * no fifth entry.
 *
 * That SVG is the PNG and GIF export target, so the disagreement left the
 * page and travelled.
 *
 * Exported from here so there is one source of phase names. `shortName` exists
 * because the legend column is 187px wide and "Final data tunnel + Data
 * Exchange" does not fit -- it is an abbreviation of `name`, not a second
 * opinion about what the phase is.
 */
export const PHASE_NAMES: { phase: number; name: string; shortName: string }[] =
  Object.entries(PHASE_BUDGETS).map(([p, info]) => ({
    phase: +p,
    name: info.name,
    shortName: PHASE_SHORT_NAMES[+p],
  }));

const TOTAL_PACKETS = Object.values(PHASE_BUDGETS).reduce((a, p) => a + p.packets, 0);
const TOTAL_BYTES = Object.values(PHASE_BUDGETS).reduce((a, p) => a + p.bytes, 0);
/**
 * The phase that carries each layer. A failure injected into a layer takes
 * effect in that phase, and MultiHopTopologySvg lights that layer's boxes and
 * connectors in that phase -- one table, so the figure cannot light a layer in
 * a phase the simulator runs something else in.
 */
export const PHASE_OF_LAYER: Readonly<Record<Layer, number>> =
  { qkd: 1, arnika: 2, wireguard: 3, rosenpass: 4, data: 5 };
const PHASE_FAIL = PHASE_OF_LAYER;
/**
 * Dwell per phase, chosen so the swimlane is watchable: four loop ticks (see
 * pacing.ts for why a dwell is a whole number of ticks).
 *
 * Exported for the same reason as e2eSim's, and it is a DIFFERENT value (400
 * here, 500 there) -- which is exactly why the CSV must carry the page's own
 * nominal rather than a shared constant. The measured column is wall-clock and
 * Chrome clamps timers to roughly 1 Hz in a hidden tab, so a background
 * recording inflates it; publishing the nominal beside it makes that visible.
 *
 * Note this is UI dwell only. It has no relation to the paper's 240-720 s
 * cascade offsets, which are simulated time and come from the "Fail-Safe
 * Mechanism" subsection of Implementation -- not from Table 1, which gives
 * packet and byte budgets.
 */
export const NOMINAL_PHASE_DWELL_MS = dwellMs(4);

/** Phase records kept in the run state; `phases_total` counts all of them. */
export const PHASE_HISTORY_LIMIT = 30;
/** Operator actions kept in the run state; `actions_total` counts all of them. */
export const ACTION_LOG_LIMIT = 50;
/**
 * How often a running cascade re-emits so its head moves between phases. The
 * timeline's own ticker ran at this cadence before the clock moved in here.
 */
const CASCADE_EMIT_MS = 500;

/** Trusted-node hops a fresh run starts with; the page's slider starts here too. */
export const DEFAULT_HOP_COUNT = 4;

/**
 * Most trusted-node hops the page offers. A layout limit, not a protocol one:
 * the topology figure gives each node a fixed-width column, and past eight the
 * exported PNG is too wide to read. One constant for the simulator, the slider
 * and the figure, which each carried their own 8.
 */
export const MAX_HOP_COUNT = 8;

interface CascadeSched {
  t_offset_s: number; layer: Layer; description: string;
  /** Wall-clock epoch seconds at which the cascade clock reached this stage, or null. */
  triggered_at: number | null;
}

/** An operator action, logged so a run log can say what was done to the run. */
export interface OperatorAction { at: number; action: string; }

export interface PaperFlowState {
  status: "idle" | "running" | "paused" | "stepped";
  current_phase: number; current_phase_name: string;
  hop_count: number;
  cycles_total: number; cycles_succeeded: number;
  packets_total: number; bytes_total: number;
  last_data_payload_b64: string;
  failure: {
    active_layer: Layer | null; started_at: number | null;
    /**
     * Cascade time: seconds the simulation has spent RUNNING since the
     * injection. Stops while paused, idle or stepped. `fired` is derived from
     * it, and FailureCascadeTimeline draws its head from it, so the two cannot
     * disagree -- they used to run on two clocks.
     */
    elapsed_s: number;
    cascade: CascadeEvent[];
  };
  history: { phase: number; name: string; started_at: number; completed_at: number | null;
             packets: number; bytes: number; detail: Record<string, unknown> }[];
  /** Phase records ever completed or opened; `history` holds the last PHASE_HISTORY_LIMIT. */
  phases_total: number;
  /** The last ACTION_LOG_LIMIT operator actions (run, pause, inject, ...). */
  operator_actions: OperatorAction[];
  actions_total: number;
  paper_budgets: { phases: PhaseBudget[]; total_handshake_packets: number;
                   total_handshake_bytes: number; mean_10_hop_setup_s: number;
                   mean_100_hop_setup_s: number };
  engine?: string;
}

/**
 * `/paper-flow`'s phase history as CSV rows.
 *
 * Here rather than inline in the page for the same reason as e2eSim's: it is
 * the only way a test can assert on the columns. Note it closes over THIS
 * module's 350 ms nominal -- importing e2eSim's 450 here would export a dwell
 * this page never uses.
 */
export function paperCsvRows(
  history: PaperFlowState["history"],
): Record<string, unknown>[] {
  return history.map((h) => ({
    phase: h.phase, name: h.name,
    started_at: new Date(h.started_at * 1000).toISOString(),
    completed_at: h.completed_at
      ? new Date(h.completed_at * 1000).toISOString() : "",
    // Wall-clock the UI sat on the phase, not a protocol timing: the dwell is
    // a fixed animation constant, and Chrome clamps timers to ~1 Hz in a
    // hidden tab. The nominal is exported beside it so a reader can spot a
    // throttled recording rather than plot it.
    ui_dwell_ms: h.completed_at
      ? Math.round((h.completed_at - h.started_at) * 1000) : "",
    nominal_dwell_ms: NOMINAL_PHASE_DWELL_MS,
    packets: h.packets, bytes: h.bytes,
  }));
}

function b64(bytes: Uint8Array): string {
  let s = ""; for (const b of bytes) s += String.fromCharCode(b);
  return btoa(s);
}

export class PaperSim {
  private status: "idle" | "running" | "paused" | "stepped" = "idle";
  private phase = 0;
  private hop = DEFAULT_HOP_COUNT;
  private cyclesTotal = 0; private cyclesSucceeded = 0;
  private packetsTotal = 0; private bytesTotal = 0;
  private lastPayload = "";
  // Key material for the phase-5 AEAD, produced by phases 2 and 4.
  private qkdKey: Uint8Array | null = null;
  private pqcSecret: Uint8Array | null = null;
  private failLayer: Layer | null = null;
  private failStarted: number | null = null;
  private cascade: CascadeSched[] = [];
  /** Running-time seconds since the injection; see PaperFlowState.failure.elapsed_s. */
  private cascadeElapsedS = 0;
  private lastTickAt: number | null = null;
  private lastCascadeEmit = 0;
  private history: PaperFlowState["history"] = [];
  private phasesTotal = 0;
  private actions: OperatorAction[] = [];
  private actionsTotal = 0;
  private cycleAccepted = true;
  private timer: number | null = null;
  private phaseStart = 0;
  private onState: (s: PaperFlowState) => void;

  constructor(onState: (s: PaperFlowState) => void) { this.onState = onState; this.emit(); }

  private budgets(): PhaseBudget[] {
    return Object.entries(PHASE_BUDGETS).map(([p, info]) => ({ phase: +p, ...info }));
  }

  snapshot(): PaperFlowState {
    return {
      status: this.status, current_phase: this.phase,
      current_phase_name: PHASE_BUDGETS[this.phase]?.name ?? "idle",
      hop_count: this.hop,
      cycles_total: this.cyclesTotal, cycles_succeeded: this.cyclesSucceeded,
      packets_total: this.packetsTotal, bytes_total: this.bytesTotal,
      last_data_payload_b64: this.lastPayload,
      failure: {
        active_layer: this.failLayer, started_at: this.failStarted,
        elapsed_s: this.cascadeElapsedS,
        cascade: this.cascade.map((c) => ({
          t_offset_s: c.t_offset_s, layer: c.layer, description: c.description,
          triggered_at: c.triggered_at, fired: this.cascadeElapsedS >= c.t_offset_s,
        })),
      },
      history: this.history.slice(-PHASE_HISTORY_LIMIT),
      phases_total: this.phasesTotal,
      operator_actions: [...this.actions],
      actions_total: this.actionsTotal,
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

  private record(action: string) {
    this.actions.push({ at: Date.now() / 1000, action });
    if (this.actions.length > ACTION_LOG_LIMIT) this.actions.shift();
    this.actionsTotal += 1;
  }

  start() {
    this.record("run");
    this.status = "running"; if (this.phase === 0) this.beginCycle(); this.ensureLoop(); this.emit();
  }
  pause() {
    this.record("pause");
    this.status = "paused";
    // Stop the timer, matching E2ESim.pause(). Leaving it running only for
    // tick() to early-return kept waking the main thread 10x a second on a
    // paused page, which on a public demo is a battery cost for nothing.
    this.stopLoop();
    this.emit();
  }
  resume() {
    this.record("resume");
    this.status = "running";
    // A Step taken while paused can finish a cycle and leave phase 0 with no
    // cycle begun (only a running sim chains into the next one). Resuming
    // from there must begin one, as start() does: the tick used to run phase
    // 0, which has no budget, and threw.
    if (this.phase === 0) this.beginCycle();
    this.ensureLoop(); this.emit();
  }

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
    this.record("step");
    // `stepped`, NOT `paused`, and not left at `idle` either.
    //
    // Measured on the deployed build: one press of Step from a fresh page
    // moved `phase` from idle to 1 while the badge still read
    // `status: idle`. The machine had advanced and the page said nothing had
    // happened -- the same defect already fixed in e2eSim, which this file
    // never received.
    //
    // Reusing `paused` is not available: it is the halted verdict here too,
    // so an operator stepping and a run dying would read identically.
    const before = this.status;
    this.status = "stepped";
    if (this.phase === 0) { this.beginCycle(); this.emit(); return; }
    this.runPhase();
    // A step from a paused run leaves it paused: the operator asked for one
    // phase, not for a resume.
    if (before === "paused") this.status = "paused";
    this.emit();
  }
  reset() {
    this.status = "idle"; this.phase = 0;
    // Stop the loop too: start() re-arms it, and a reset run has nothing to tick.
    this.stopLoop();
    this.cyclesTotal = this.cyclesSucceeded = this.packetsTotal = this.bytesTotal = 0;
    this.lastPayload = ""; this.failLayer = null; this.failStarted = null;
    this.qkdKey = null; this.pqcSecret = null;
    this.cascade = []; this.cascadeElapsedS = 0;
    this.history = []; this.phasesTotal = 0; this.cycleAccepted = true;
    // The action log restarts with the run it describes, beginning with the reset.
    this.actions = []; this.actionsTotal = 0; this.record("reset");
    this.emit();
  }
  setHopCount(n: number) {
    this.hop = Math.max(1, Math.min(MAX_HOP_COUNT, Math.round(n)));
    this.record(`hops=${this.hop}`);
    this.emit();
  }
  // `setDualPath` was here, with a `dual` field and a `dual_path` state
  // field. It was reachable from no UI control, and `this.dual` appeared
  // exactly twice in this file -- the setter and the state emission -- so it
  // changed no packet count, no timing and no phase. It was reported into the
  // citable run log as `dual_path: false`, which reads as "there is a second
  // path and it is off" rather than "this concept is not modelled".
  //
  // Removed rather than wired to a control. Nothing in docs/, tests/ or the
  // referenced paper asks for it (the only "dual" in the documentation is
  // dual-KEM in paper_mapping.md, an unrelated idea), so a toggle would have
  // been a new control that appears to do something and does nothing -- the
  // same defect as `/sim/eve` reporting success on a backend that ignores it.

  injectFailure(layer: Layer) {
    const now = Date.now() / 1000;
    const startIdx = Math.max(0, CASCADE_STAGES.findIndex((s) => s[1] === layer));
    const baseT = CASCADE_STAGES[startIdx][0];
    this.record(`inject ${layer}`);
    this.failLayer = layer; this.failStarted = now;
    // The cascade clock starts at zero and advances only while running. The
    // first stage is the injection itself, so it has fired at t = 0.
    this.cascadeElapsedS = 0;
    this.cascade = CASCADE_STAGES.slice(startIdx).map(([t, l, d]) => ({
      t_offset_s: t - baseT, layer: l, description: d,
      triggered_at: t === baseT ? now : null,
    }));
    this.emit();
  }
  clearFailure() {
    this.record("clear failure");
    this.failLayer = null; this.failStarted = null; this.cascade = []; this.cascadeElapsedS = 0;
    this.emit();
  }

  /** Stop the tick timer. Idempotent. */
  private stopLoop() {
    if (this.timer !== null) { clearInterval(this.timer); this.timer = null; }
  }

  dispose() { this.stopLoop(); }

  private ensureLoop() {
    if (this.timer !== null) return;
    this.phaseStart = performance.now();
    // A resume must not credit the paused gap to the cascade clock.
    this.lastTickAt = this.phaseStart;
    this.timer = window.setInterval(() => this.tick(), LOOP_TICK_MS);
  }
  private beginCycle() {
    this.cyclesTotal += 1; this.cycleAccepted = true;
    // Each cycle establishes its own key material; nothing carries over from
    // the previous cycle into this one's phase 5.
    this.qkdKey = null; this.pqcSecret = null;
    this.enterPhase(1);
  }

  private tick() {
    if (this.status !== "running") return;
    const now = performance.now();
    if (this.failLayer !== null && this.lastTickAt !== null) {
      this.advanceCascade((now - this.lastTickAt) / 1000);
    }
    this.lastTickAt = now;
    if (dwellDone(now - this.phaseStart, NOMINAL_PHASE_DWELL_MS)) this.runPhase();
    else if (this.failLayer !== null && now - this.lastCascadeEmit >= CASCADE_EMIT_MS) {
      this.lastCascadeEmit = now;
      this.emit();
    }
  }

  /** Advance the cascade clock by `dt` running seconds and stamp stages it reaches. */
  private advanceCascade(dt: number) {
    this.cascadeElapsedS += dt;
    const wall = Date.now() / 1000;
    for (const c of this.cascade) {
      if (c.triggered_at === null && this.cascadeElapsedS >= c.t_offset_s) c.triggered_at = wall;
    }
  }

  private enterPhase(phase: number) {
    this.phase = phase;
    this.history.push({ phase, name: PHASE_BUDGETS[phase].name,
      started_at: Date.now() / 1000, completed_at: null, packets: 0, bytes: 0, detail: {} });
    this.phasesTotal += 1;
    if (this.history.length > PHASE_HISTORY_LIMIT) this.history = this.history.slice(-PHASE_HISTORY_LIMIT);
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

    // Phase 2 yields the QKD key, phase 4 the PQC secret, each where the
    // modelled flow produces it. In the paper the two never meet: QKD keys
    // are hop-local (phase 3 keys the hop tunnel with them) and the Rosenpass
    // output alone keys the end-to-end tunnel (phase 5). Phase 5 used to
    // derive its PSK from HKDF(qkd || pqc), which is this repository's arnika
    // lane, not the paper's layering -- Alice and Bob never share a QKD key
    // across trusted nodes.
    if (phase === 2 && !failedThisPhase) this.qkdKey = randomBytes(32);
    if (phase === 3 && !failedThisPhase && this.qkdKey) {
      detail.hop_psk_prefix = toHex(
        deriveHkdfSha3(this.qkdKey, new Uint8Array(0), "paper-flow-hop")).slice(0, 16);
    }
    if (phase === 4 && !failedThisPhase) this.pqcSecret = randomBytes(32);

    if (phase === 5 && !failedThisPhase) {
      // PHASE_BUDGETS[5] describes this as "WireGuard with ChaCha20-Poly1305
      // ... a PSK derived from the Rosenpass output", and the page titles the
      // panel accordingly. Previously the payload was plain randomBytes(64) and
      // no AEAD ran at all, so the label asserted a cryptographic property the
      // code did not provide. Do what the description says.
      //
      // A cycle reaches phase 5 only after its own phase 4 succeeded: a failure
      // ends the cycle in the failing phase, and beginCycle() clears the keys.
      // So a missing secret here is a bug in this file, not a run condition.
      const pqc = this.pqcSecret;
      if (!pqc) throw new Error("paperSim: phase 5 reached without this cycle's PQC secret");
      const psk = deriveHkdfSha3(new Uint8Array(0), pqc, "paper-flow");
      // cyclesTotal was incremented when this cycle began, so it already
      // numbers this cycle.
      const plaintext = encodeUtf8(
        `PAPER-FLOW cycle ${this.cyclesTotal} hops=${this.hop} Alice->Bob`);
      const { ciphertext, nonce } = chachaSeal(psk, plaintext);
      pkts = 1;
      // On the wire the nonce travels with the ciphertext, so both count.
      bytes = ciphertext.length + nonce.length;
      this.lastPayload = b64(ciphertext);
      detail.data_bytes = bytes;
      detail.aead = "ChaCha20-Poly1305";
      detail.psk_source = "Rosenpass output only (HKDF-SHA3-256)";
      detail.psk_prefix = toHex(psk).slice(0, 16);
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
