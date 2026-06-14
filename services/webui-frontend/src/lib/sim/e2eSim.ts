/**
 * Client-side E2E orchestrator (Round 5) — TS port of the 4-phase
 * services/webui-backend/app/e2e_orchestrator.py state machine, run entirely in
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
  history: PhaseRec[];
  engine?: string;
}

const PHASE_NAMES: Record<number, string> = {
  1: "Quantum Plane",
  2: "QKD Key IDs (ETSI 014)",
  3: "PQC Handshake (HKDF-SHA3-256)",
  4: "Data Exchange (ChaCha20-Poly1305)",
};
const MODE_LABEL: Record<Mode, string> = {
  A: "QKD-only", B: "PQC-only", C: "Hybrid (QKD ‖ PQC)",
};
const N_PACKETS = 64;
const PHASE_MS = 450;          // dwell per phase so the animation is watchable

export class E2ESim {
  private s: E2EState;
  private timer: number | null = null;
  private phaseStart = 0;
  private cycleStart = 0;
  private qkdKey = new Uint8Array(0);
  private pqcSecret = new Uint8Array(0);
  private derived = new Uint8Array(0);
  private keyId = "";
  private cycleBytes = 0;
  private stepPending = false;
  private onState: (s: E2EState) => void;

  constructor(onState: (s: E2EState) => void) {
    this.onState = onState;
    this.s = this.fresh("C");
  }

  private fresh(mode: Mode): E2EState {
    return {
      status: "idle", current_phase: 0, phase_name: "idle", mode,
      mode_label: MODE_LABEL[mode], completed_cycles: 0,
      total_bytes_encrypted: 0, total_packets: 0, last_qkd_key_id: "",
      last_psk_prefix_hex: "", last_error: "", rate_bps: 0, history: [],
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
  pause() { this.s.status = "paused"; this.emit(); }
  resume() { this.s.status = "running"; this.ensureLoop(); this.emit(); }
  reset() {
    const mode = this.s.mode;
    this.s = this.fresh(mode);
    this.qkdKey = this.pqcSecret = this.derived = new Uint8Array(0);
    this.cycleBytes = 0; this.keyId = "";
    this.emit();
  }
  step() { this.stepPending = true; if (this.s.current_phase === 0) this.enter(1); this.runPhaseWork(); this.advance(true); this.emit(); }
  setMode(m: Mode) { this.s.mode = m; this.s.mode_label = MODE_LABEL[m]; this.emit(); }

  dispose() { if (this.timer !== null) { clearInterval(this.timer); this.timer = null; } }

  private ensureLoop() {
    if (this.timer !== null) return;
    this.phaseStart = performance.now();
    this.cycleStart = performance.now();
    this.timer = window.setInterval(() => this.tick(), 100);
  }

  private tick() {
    if (this.s.status !== "running") return;
    if (performance.now() - this.phaseStart >= PHASE_MS) {
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

  /** Do the actual crypto/work for the CURRENT phase. */
  private runPhaseWork() {
    const mode = this.s.mode;
    switch (this.s.current_phase) {
      case 1:
        this.exit({ alice_pool: 1 + Math.floor(Math.random() * 8) });
        break;
      case 2:
        if (mode === "A" || mode === "C") {
          this.qkdKey = randomBytes(32);
          this.keyId = crypto.randomUUID();
        } else { this.qkdKey = new Uint8Array(0); this.keyId = "(PQC-only mode)"; }
        this.exit({ key_id: this.keyId, qkd_key_len: this.qkdKey.length });
        break;
      case 3:
        this.pqcSecret = (mode === "B" || mode === "C") ? randomBytes(32) : new Uint8Array(0);
        this.derived = deriveHkdfSha3(this.qkdKey, this.pqcSecret, mode);
        this.s.last_psk_prefix_hex = toHex(this.derived).slice(0, 16);
        this.exit({ psk_prefix: this.s.last_psk_prefix_hex,
          qkd_bytes: this.qkdKey.length, pqc_bytes: this.pqcSecret.length });
        break;
      case 4: {
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
        this.s.rate_bps = (bytes * 8.0) / elapsed;
        this.s.last_error = "";
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
      if (stepping) this.stepPending = false;
    } else {
      this.enter(cur + 1);
    }
  }
}
