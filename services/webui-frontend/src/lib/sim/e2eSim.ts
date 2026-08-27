/**
 * Client-side E2E orchestrator (Round 5) — TS port of the 4-phase
 * the former services/webui-backend/app/e2e_orchestrator.py state machine (that
 * module has since been deleted; this is now the only implementation), run in
 * the browser with REAL crypto (HKDF-SHA3-256 + ChaCha20-Poly1305 via @noble).
 * Emits the same E2EState shape the page already renders, so no UI changes.
 */
import { chachaEncrypt, deriveHkdfSha3, encodeUtf8, randomBytes, toHex } from "./crypto";

export type Mode = "A" | "B" | "C";

export interface PhaseRec {
  phase: number; name: string;
  started_at: number; completed_at: number | null;
  detail: Record<string, unknown>;
}

export interface E2EState {
  status: "idle" | "running" | "paused";
  /** Layer the operator has knocked out, or null. See `injectFailure`. */
  failed_layer: E2ELayer | null;
  /**
   * Whether that failure ends the run, decided by the simulator.
   *
   * Published rather than left for the view to work out. The page originally
   * recomputed it in JSX as "mode C degrades, anything else is fatal", which
   * is wrong for the two cells where a mode never used the failed layer --
   * mode A with PQC down was labelled fatal on screen while the run carried
   * on. One rule, one owner.
   */
  failure_is_fatal: boolean;
  current_phase: number;
  phase_name: string;
  mode: Mode;
  mode_label: string;
  completed_cycles: number;
  total_bytes_encrypted: number;
  total_packets: number;
  last_qkd_key_id: string;
  last_psk_prefix_hex: string;
  last_error: string;
  rate_bps: number;
  /**
   * The cycle length the animation is paced to, in ms.
   *
   * Beside `rate_bps` so the reader can tell a throttled recording from a slow
   * one: `rate_bps` divides by measured wall-clock, and a hidden tab inflates
   * that denominator. See the comment at the assignment.
   */
  nominal_cycle_ms: number;
  history: PhaseRec[];
  engine?: string;
}

const PHASE_NAMES: Record<number, string> = {
  1: "Quantum Plane",
  2: "QKD Key IDs (ETSI 014)",
  3: "PQC Handshake (HKDF-SHA3-256)",
  4: "Data Exchange (ChaCha20-Poly1305)",
};
/**
 * A layer the operator can knock out.
 *
 * `/paper-flow` models failure as a cascade down a multi-hop chain, which is
 * what its paper describes. Here the interesting behaviour is different and
 * more to the point of this project: whether a knocked-out layer stops the run
 * depends on the MODE. Mode C keeps going on one leg when the other dies,
 * which is the entire claim a hybrid makes; modes A and B cannot.
 */
export type E2ELayer = "qkd" | "pqc" | "data";

const MODE_LABEL: Record<Mode, string> = {
  A: "QKD-only", B: "PQC-only", C: "Hybrid (QKD ‖ PQC)",
};
const N_PACKETS = 64;

/**
 * Dwell per phase, chosen so the animation is watchable.
 *
 * Exported because the CSV carries the MEASURED wall-clock time each phase
 * occupied, and without the nominal value beside it that column reads as a
 * protocol measurement. It is not one: it is this constant, and the browser
 * distorts it. Chrome clamps `setInterval` to roughly 1 Hz in a hidden tab, so
 * a run recorded with the tab in the background reports ~1000 ms per phase
 * against a 450 ms nominal -- observed on the deployed demo, where phases that
 * should take 450 ms logged 999 ms.
 *
 * Publishing both lets a reader see the distortion instead of plotting it.
 */
export const NOMINAL_PHASE_DWELL_MS = 450;

/**
 * `/e2e`'s phase history as CSV rows.
 *
 * Here, not inside the page component, so a test can call the thing that
 * actually builds the file. While this was a closure over `state` the only
 * symbol a test could reach was the dwell constant, so the guard written to
 * keep `duration_ms` from coming back could not see a single exported column.
 */
export function e2eCsvRows(history: PhaseRec[]): Record<string, unknown>[] {
  return history.map((h) => ({
    phase: h.phase,
    name: h.name,
    started_at: new Date(h.started_at * 1000).toISOString(),
    completed_at: h.completed_at
      ? new Date(h.completed_at * 1000).toISOString() : "",
    // Named for what it is. This is the wall-clock time the UI sat on the
    // phase, not a protocol timing: the dwell is a fixed animation constant,
    // and Chrome clamps timers to ~1 Hz in a hidden tab, so a run recorded in
    // a background tab logs ~1000 ms against a 450 ms nominal -- observed on
    // the deployed demo. Exporting the nominal beside it lets a reader detect
    // that distortion instead of plotting it as a measurement.
    ui_dwell_ms: h.completed_at
      ? Math.round((h.completed_at - h.started_at) * 1000) : "",
    nominal_dwell_ms: NOMINAL_PHASE_DWELL_MS,
    // One column per detail key rather than a JSON blob, so the CSV is
    // usable in a spreadsheet without post-processing.
    ...h.detail,
  }));
}

export class E2ESim {
  /** Pool ceiling, so a long run reports a bounded depth rather than a ramp. */
  static readonly KEY_POOL_CAPACITY = 8;

  private s: E2EState;
  private timer: number | null = null;
  private phaseStart = 0;
  private cycleStart = 0;
  // Annotated explicitly: `new Uint8Array(0)` infers the narrower
  // Uint8Array<ArrayBuffer>, while @noble's helpers return the general
  // Uint8Array<ArrayBufferLike>, so inference alone makes assignment fail.
  private qkdKey: Uint8Array = new Uint8Array(0);
  private pqcSecret: Uint8Array = new Uint8Array(0);
  private derived: Uint8Array = new Uint8Array(0);
  private keyId = "";
  private cycleBytes = 0;
  /**
   * Depth of Alice's QKD key pool, as a real quantity.
   *
   * Phase 1 reported `1 + Math.floor(Math.random() * 8)` here, and that number
   * was surfaced in the phase-history table and in the JSON and CSV exports as
   * if it were a measurement. It is now driven by the run: the quantum plane
   * deposits a key each cycle, and the ETSI 014 exchange in phase 2 draws one,
   * so the depth reflects what the simulation actually did.
   */
  private alicePool = 0;
  private onState: (s: E2EState) => void;

  constructor(onState: (s: E2EState) => void) {
    this.onState = onState;
    this.s = this.fresh("C");
  }

  private fresh(mode: Mode): E2EState {
    return {
      status: "idle", current_phase: 0, phase_name: "idle", mode, failed_layer: null,
      failure_is_fatal: false,
      mode_label: MODE_LABEL[mode], completed_cycles: 0,
      total_bytes_encrypted: 0, total_packets: 0, last_qkd_key_id: "",
      last_psk_prefix_hex: "", last_error: "", rate_bps: 0,
      nominal_cycle_ms: 4 * NOMINAL_PHASE_DWELL_MS, history: [],
      engine: "client-side (JS + @noble)",
    };
  }

  private emit() { this.onState({ ...this.s, history: [...this.s.history] }); }

  start() {
    this.s.status = "running";
    if (this.s.current_phase === 0) this.enter(1);
    this.ensureLoop();
    this.emit();
  }
  /** Freeze the run, keeping all state so resume() can continue it. */
  pause() {
    this.s.status = "paused";
    // Stop the timer rather than letting tick() early-return on every fire:
    // a paused simulation should not keep waking the main thread 10x a second.
    this.stopLoop();
    this.emit();
  }

  resume() { this.s.status = "running"; this.ensureLoop(); this.emit(); }

  /** Return to the initial state, discarding key material and history. */
  reset() {
    // Stop the loop first. Previously reset() left the interval running, so
    // the next start() found a live timer, ensureLoop() short-circuited, and
    // phaseStart/cycleStart were never re-seeded -- making the first phase
    // after a reset finish early and the throughput figure meaningless.
    this.stopLoop();
    const mode = this.s.mode;
    this.s = this.fresh(mode);
    this.clearKeyMaterial();
    this.cycleBytes = 0; this.keyId = ""; this.alicePool = 0;
    this.emit();
  }

  /**
   * Stop the run and wipe derived key material, without clearing the counters
   * that record what happened. This is the "stop and leave the evidence"
   * control that Reset deliberately is not.
   */
  abort() {
    this.stopLoop();
    this.s.status = "idle";
    this.s.current_phase = 0;
    this.s.phase_name = "aborted";
    this.clearKeyMaterial();
    this.cycleBytes = 0; this.keyId = "";
    this.s.last_error = "Run aborted by operator";
    this.emit();
  }
  /**
   * Advance exactly one phase.
   *
   * Refuses while running. It previously did not check status, so pressing
   * Step during a run advanced the machine underneath the timer and the badge
   * still read "running" -- two things driving the same state machine.
   */
  step() {
    if (this.s.status === "running") return;
    if (this.s.current_phase === 0) this.enter(1);
    this.runPhaseWork();
    this.advance(true);
    this.emit();
  }
  setMode(m: Mode) {
    this.s.mode = m;
    this.s.mode_label = MODE_LABEL[m];
    // The same failed layer is fatal in one mode and harmless in another, so
    // the verdict is re-derived here rather than only at injection time.
    this.s.failure_is_fatal = this.failureIsFatal();
    this.emit();
  }

  dispose() { this.stopLoop(); this.clearKeyMaterial(); }

  private stopLoop() {
    if (this.timer !== null) { clearInterval(this.timer); this.timer = null; }
  }

  /** Drop references to key material. Zero the buffers first: even in a
   *  simulation, leaving derived keys reachable from a live object is a habit
   *  worth not forming. */
  private clearKeyMaterial() {
    this.qkdKey.fill(0); this.pqcSecret.fill(0); this.derived.fill(0);
    this.qkdKey = new Uint8Array(0);
    this.pqcSecret = new Uint8Array(0);
    this.derived = new Uint8Array(0);
  }

  private ensureLoop() {
    if (this.timer !== null) return;
    this.phaseStart = performance.now();
    this.cycleStart = performance.now();
    this.timer = window.setInterval(() => this.tick(), 100);
  }

  private tick() {
    if (this.s.status !== "running") return;
    if (performance.now() - this.phaseStart >= NOMINAL_PHASE_DWELL_MS) {
      this.runPhaseWork();
      this.advance(false);
      this.emit();
    }
  }

  private enter(phase: number) {
    this.s.current_phase = phase;
    this.s.phase_name = PHASE_NAMES[phase] ?? "idle";
    if (phase === 1) { this.cycleStart = performance.now(); this.cycleBytes = 0; }
    this.s.history.push({ phase, name: PHASE_NAMES[phase] ?? "",
      started_at: Date.now() / 1000, completed_at: null, detail: {} });
    if (this.s.history.length > 20) this.s.history = this.s.history.slice(-20);
    this.phaseStart = performance.now();
  }

  private exit(detail: Record<string, unknown>) {
    for (let i = this.s.history.length - 1; i >= 0; i--) {
      if (this.s.history[i].phase === this.s.current_phase
          && this.s.history[i].completed_at === null) {
        this.s.history[i].completed_at = Date.now() / 1000;
        this.s.history[i].detail = detail;
        break;
      }
    }
  }

  /**
   * Knock out a layer, and let the mode decide whether that ends the run.
   *
   * Deliberately not a cascade: on a single tunnel there is nothing to cascade
   * through. What this shows instead is the layered-security argument the
   * project rests on -- in hybrid mode, losing the QKD leg degrades the run to
   * PQC-only rather than stopping it, and losing the PQC leg degrades it to
   * QKD-only. In single-source modes the same injection aborts, because there
   * is no second leg to fall back to.
   */
  injectFailure(layer: E2ELayer) {
    this.s.failed_layer = layer;
    this.s.failure_is_fatal = this.failureIsFatal();
    this.emit();
  }

  clearFailure() {
    this.s.failed_layer = null;
    this.s.failure_is_fatal = false;
    this.s.last_error = "";
    this.emit();
  }

  /** True when the run cannot continue: the failed layer is the only source. */
  private failureIsFatal(): boolean {
    const f = this.s.failed_layer;
    if (!f) return false;
    if (f === "data") return true;              // AEAD is not duplicated
    // Fatal only where the failed layer was the mode's ONLY key source.
    // Mode C has both legs, so neither single-leg failure is fatal for it --
    // that is the whole point of the hybrid, and writing this as
    // `mode !== "B"` inverted it and made C the most fragile mode.
    if (f === "qkd") return this.s.mode === "A";   // A is QKD-only
    return this.s.mode === "B";                    // f === "pqc"; B is PQC-only
  }

  /** Do the actual crypto/work for the CURRENT phase. */
  private runPhaseWork() {
    const mode = this.s.mode;
    switch (this.s.current_phase) {
      case 1:
        if (this.s.failed_layer === "qkd") {
          // No key material is produced at all; the pool cannot grow.
          this.exit({ alice_pool: this.alicePool, failed: "qkd" });
          break;
        }
        // Quantum plane: the QKD device deposits key material into the pool.
        this.alicePool = Math.min(this.alicePool + 1, E2ESim.KEY_POOL_CAPACITY);
        this.exit({ alice_pool: this.alicePool });
        break;
      case 2:
        if (this.s.failed_layer === "qkd") {
          this.qkdKey = new Uint8Array(0);
          this.keyId = "(QKD layer failed)";
          this.exit({ key_id: this.keyId, qkd_key_len: 0, failed: "qkd",
                      alice_pool: this.alicePool });
          break;
        }
        if (mode === "A" || mode === "C") {
          this.qkdKey = randomBytes(32);
          this.keyId = crypto.randomUUID();
          // The ETSI 014 exchange consumes one key from the pool. Modes that
          // use no QKD key draw nothing, which is why the depth differs
          // between modes rather than drifting the same way in all of them.
          this.alicePool = Math.max(0, this.alicePool - 1);
        } else { this.qkdKey = new Uint8Array(0); this.keyId = "(PQC-only mode)"; }
        this.exit({ key_id: this.keyId, qkd_key_len: this.qkdKey.length,
                    alice_pool: this.alicePool });
        break;
      case 3:
        this.pqcSecret = (this.s.failed_layer === "pqc" || mode === "A")
          ? new Uint8Array(0)
          : randomBytes(32);
        // The derivation still runs on whatever survives. With ONE leg gone the
        // PSK is weaker, not absent -- that is the property being demonstrated,
        // so it is shown rather than short-circuited.
        //
        // With BOTH gone there is nothing to derive from, and HKDF will not say
        // so: over a zero-length IKM it returns a value fixed entirely by the
        // public salt and info, identical on every run. Two of the nine mode x
        // failure cells reach that state -- mode A with QKD down, mode B with
        // PQC down -- and both used to display its prefix under the heading
        // "Latest derived WireGuard PSK". A public constant in the slot the page
        // labels key material. Report the absence instead; see
        // e2eEmptyIkm.test.ts, which pins the two cells by name.
        if (this.qkdKey.length === 0 && this.pqcSecret.length === 0) {
          this.derived = new Uint8Array(0);
          this.s.last_psk_prefix_hex = "";
          this.exit({
            psk_prefix: null, qkd_bytes: 0, pqc_bytes: 0,
            note: "no key material survived; HKDF over an empty IKM would return "
                + "a fixed public constant, not a secret",
          });
          break;
        }
        this.derived = deriveHkdfSha3(this.qkdKey, this.pqcSecret, mode);
        this.s.last_psk_prefix_hex = toHex(this.derived).slice(0, 16);
        this.exit({ psk_prefix: this.s.last_psk_prefix_hex,
          qkd_bytes: this.qkdKey.length, pqc_bytes: this.pqcSecret.length });
        break;
      case 4: {
        if (this.failureIsFatal()) {
          // Nothing survives to key the tunnel. Stop, and say which layer and
          // why -- a run that silently produced no bytes would look like the
          // simulator had hung.
          const f = this.s.failed_layer;
          this.s.last_error = f === "data"
            ? "Data layer failed: AEAD cannot encrypt (no fallback exists)"
            : `${f!.toUpperCase()} layer failed and mode ${mode} has no other key source`;
          this.s.status = "paused";
          this.stopLoop();
          this.exit({ packets: 0, bytes: 0, failed: f, fatal: true });
          this.emit();
          break;
        }
        let bytes = 0;
        for (let i = 0; i < N_PACKETS; i++) {
          const payload = encodeUtf8(`PING ${i} Alice->Bob over Quantum-Secure VPN`);
          const { ctLen, nonceLen } = chachaEncrypt(this.derived, payload);
          bytes += ctLen + nonceLen;
        }
        this.cycleBytes = bytes;
        const elapsed = Math.max((performance.now() - this.cycleStart) / 1000, 1e-3);
        this.s.total_bytes_encrypted += bytes;
        this.s.total_packets += N_PACKETS;
        this.s.completed_cycles += 1;
        this.s.last_qkd_key_id = this.keyId;
        // Bits per second over WALL-CLOCK, which the browser throttles.
        //
        // The arithmetic and the units are right -- bytes x 8 / seconds -- but
        // the denominator is measured, and Chrome clamps timers to about 1 Hz
        // in a hidden tab. Measured on the demo: 4470 bytes reported at
        // 8952 bps, implying 3.995 s for a cycle whose nominal length is
        // 4 x 450 ms = 1.8 s. So a backgrounded run understates throughput by
        // roughly the throttle ratio.
        //
        // `nominal_cycle_ms` is published beside it for the same reason
        // `nominal_dwell_ms` is published beside `ui_dwell_ms`: a reader can
        // compare the two and see whether the recording was throttled, instead
        // of taking the rate for a property of the system.
        this.s.rate_bps = (bytes * 8.0) / elapsed;
        this.s.nominal_cycle_ms = 4 * NOMINAL_PHASE_DWELL_MS;
        this.s.last_error = this.s.failed_layer
          ? `Degraded: ${this.s.failed_layer.toUpperCase()} layer failed; `
            + `mode ${mode} continued on the surviving leg`
          : "";
        this.exit({ packets: N_PACKETS, bytes, rate_mbps: (bytes * 8.0) / elapsed / 1e6 });
        break;
      }
    }
  }

  /** Move to the next phase (or finish a cycle). */
  private advance(stepping: boolean) {
    const cur = this.s.current_phase;
    if (cur >= 4) {
      this.s.current_phase = 0;
      this.s.phase_name = "idle";
      if (this.s.status === "running" && !stepping) this.enter(1);   // loop
    } else {
      this.enter(cur + 1);
    }
  }
}
