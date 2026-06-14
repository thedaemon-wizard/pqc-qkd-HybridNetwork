/**
 * BB84 engine controller (Round 5/5b). Streams {qber, pool_size, frames} to the
 * page (same shape the old /ws/frames delivered) plus the active engine name and
 * throughput. Engine selection is ADAPTIVE and measured:
 *
 *   1. Start on the CPU Web Worker immediately (instant data, never blocks UI).
 *   2. Try the GPU tiers in order — WebGPU (compute) then WebGL2 (GPGPU) — and
 *      benchmark each one round. Adopt a GPU tier ONLY if it is measurably faster
 *      than the CPU Worker (≥15% margin); otherwise keep the Worker.
 *
 * So a missing GPU, or a slow software rasteriser (SwiftShader), never degrades
 * performance — the demo always runs at the fastest available client-side speed.
 * Diagnose-before-fallback: real init/shader errors are logged verbatim.
 */
import { Bb84Gpu, type Bb84Cfg } from "./bb84Gpu";
import { Bb84Gl } from "./bb84Gl";

export interface Bb84Frame {
  i: number; alice_bit: number; alice_basis: number;
  bob_basis: number; bob_bit: number; basis_match: boolean;
}
export interface Bb84Update {
  qber: number; pool_size: number; frames: Bb84Frame[];
  engine: string; pulsesPerSec: number;
}

const DEFAULT_CFG: Bb84Cfg = {
  etaTotal: 0.02, eD: 0.015, Y0: 1e-5,
  eveOn: false, eveProb: 1.0, pulsesPerRound: 1_000_000,
};
const UPGRADE_MARGIN = 1.15;       // a GPU tier must beat the CPU by ≥15% to be used

export class Bb84Engine {
  private cfg: Bb84Cfg = { ...DEFAULT_CFG };
  private worker: Worker | null = null;
  private gpu: Bb84Gpu | null = null;
  private gl: Bb84Gl | null = null;
  private running = false;
  private upgraded = false;
  private gpuTimer: number | null = null;
  private workerPps = 0;
  private onUpdate: (u: Bb84Update) => void;

  constructor(onUpdate: (u: Bb84Update) => void) { this.onUpdate = onUpdate; }

  setConfig(partial: Partial<Bb84Cfg>) {
    this.cfg = { ...this.cfg, ...partial };
    if (this.worker) this.worker.postMessage({ type: "config", params: this.cfg });
  }

  async start() {
    if (this.running) return;
    this.running = true;
    this.startWorker();                                   // instant CPU data
    // After the Worker reports its rate, try to upgrade to a faster GPU tier.
    window.setTimeout(() => this.tryUpgrade(), 1300);
  }

  /** Benchmark WebGPU then WebGL2; adopt whichever clearly beats the CPU Worker. */
  private async tryUpgrade() {
    if (!this.running || this.upgraded) return;
    const target = Math.max(this.workerPps, 1) * UPGRADE_MARGIN;

    try {                                                 // ── WebGPU ──
      const gpu = new Bb84Gpu();
      if (await gpu.init()) {
        const r = await gpu.runRound(this.cfg);           // one benchmark round
        if (r.pulsesPerSec >= target) { this.adoptGpu(gpu); return; }
        console.info(`[bb84] WebGPU ${fmt(r.pulsesPerSec)} ≤ Worker ${fmt(this.workerPps)} — keeping Worker`);
        gpu.dispose();
      }
    } catch (e) {
      console.warn("[bb84] WebGPU init/bench failed — investigate before relying on fallback:", e);
    }

    try {                                                 // ── WebGL2 GPGPU ──
      const gl = new Bb84Gl();
      if (gl.init()) {
        const r = gl.runRound(this.cfg);                  // one benchmark round
        if (r.pulsesPerSec >= target) { this.adoptGl(gl); return; }
        console.info(`[bb84] WebGL ${fmt(r.pulsesPerSec)} ≤ Worker ${fmt(this.workerPps)} — keeping Worker`);
        gl.dispose();
      }
    } catch (e) {
      console.warn("[bb84] WebGL init/bench failed — investigate before relying on fallback:", e);
    }
    // else: keep the CPU Worker (already running)
  }

  private adoptGpu(gpu: Bb84Gpu) {
    this.upgraded = true; this.gpu = gpu; this.stopWorker(); this.gpuLoop("WebGPU (compute shader)");
  }
  private adoptGl(gl: Bb84Gl) {
    this.upgraded = true; this.gl = gl; this.stopWorker();
    this.glLoop("WebGL2 (GPGPU)");
  }

  private async gpuLoop(engine: string) {
    if (!this.running || !this.gpu) return;
    try {
      const r = await this.gpu.runRound(this.cfg);
      this.onUpdate({ ...r, engine });
    } catch (e) {
      console.warn("[bb84] WebGPU runRound failed — reverting to Worker:", e);
      this.gpu?.dispose(); this.gpu = null; this.upgraded = false; this.startWorker(); return;
    }
    if (this.running) this.gpuTimer = window.setTimeout(() => this.gpuLoop(engine), 250);
  }

  private glLoop(engine: string) {
    if (!this.running || !this.gl) return;
    try {
      const r = this.gl.runRound(this.cfg);
      this.onUpdate({ ...r, engine });
    } catch (e) {
      console.warn("[bb84] WebGL runRound failed — reverting to Worker:", e);
      this.gl?.dispose(); this.gl = null; this.upgraded = false; this.startWorker(); return;
    }
    if (this.running) this.gpuTimer = window.setTimeout(() => this.glLoop(engine), 250);
  }

  private startWorker() {
    if (this.worker) return;
    this.worker = new Worker(new URL("./bb84.worker.ts", import.meta.url), { type: "module" });
    this.worker.onmessage = (ev: MessageEvent) => {
      const m = ev.data;
      if (m.type === "frames") {
        this.workerPps = m.pulsesPerSec;
        this.onUpdate({ qber: m.qber, pool_size: m.pool_size, frames: m.frames,
          engine: m.engine, pulsesPerSec: m.pulsesPerSec });
      }
    };
    this.worker.postMessage({ type: "config", params: this.cfg });
    this.worker.postMessage({ type: "start" });
  }
  private stopWorker() {
    if (!this.worker) return;
    this.worker.postMessage({ type: "stop" });
    this.worker.terminate();
    this.worker = null;
  }

  stop() {
    this.running = false;
    if (this.gpuTimer !== null) { clearTimeout(this.gpuTimer); this.gpuTimer = null; }
    this.stopWorker();
  }

  dispose() {
    this.stop();
    this.gpu?.dispose(); this.gpu = null;
    this.gl?.dispose(); this.gl = null;
  }
}

const fmt = (p: number) => `${(p / 1e6).toFixed(0)}M/s`;
