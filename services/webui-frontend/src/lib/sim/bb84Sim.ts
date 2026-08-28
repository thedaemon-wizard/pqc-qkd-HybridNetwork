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
import { bundledChannel } from "./keyrate";

export interface Bb84Frame {
  i: number; alice_bit: number; alice_basis: number;
  bob_basis: number; bob_bit: number; basis_match: boolean;
}
/**
 * What happened when a GPU tier was tried.
 *
 * The selection was measured and then thrown away: the outcome went to
 * `console.info` and nowhere else, so the page showed `Worker (CPU)` with
 * nothing to say that WebGPU had been built, initialised and benchmarked.
 * Measured on the deployed demo 2026-08-28, five consecutive rounds:
 *
 *     [bb84] WebGPU 33M/s <= Worker 42M/s -- keeping Worker
 *     [bb84] WebGPU 50M/s <= Worker 61M/s -- keeping Worker
 *
 * A reader with the page open concludes the compute-shader path does not
 * exist. It does, it ran, and it lost on this hardware -- which is a result,
 * not an absence, and exactly the kind of thing this project otherwise puts on
 * screen. The same defect `/benchmarks` had with `skr_provenance`.
 */
export interface TierTrial {
  tier: string;
  /** Benchmarked rate, or null when the tier could not be initialised. */
  pulsesPerSec: number | null;
  adopted: boolean;
  /** Present only when init or the benchmark threw. Never a bare "failed". */
  error?: string;
}

export interface Bb84Update {
  qber: number; pool_size: number; frames: Bb84Frame[];
  engine: string; pulsesPerSec: number;
  /** Empty until the upgrade pass has run; never undefined. */
  tierTrials: TierTrial[];
  /** The CPU rate the tiers were compared against, once known. */
  workerPulsesPerSec: number | null;
}

// Derived from the one bundled parameter set, not restated. These used to be
// literals describing a channel 6.3x more lossy than the configured one.
const DEFAULT_CFG: Bb84Cfg = {
  ...bundledChannel(),
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
  /** Every tier tried, in order, with the rate it achieved. Surfaced. */
  private trials: TierTrial[] = [];
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

  /**
   * Record one tier's outcome, at most once.
   *
   * Deduplicated by tier because the failure paths overlap: a `dispose()` that
   * throws after a successful benchmark lands in the same `catch` as an
   * `init()` that threw, and a second push for the same tier both duplicated
   * the React key and showed the reader that tier twice, once with a rate and
   * once with an error.
   */
  private record(t: TierTrial) {
    if (this.trials.some((x) => x.tier === t.tier)) return;
    this.trials.push(t);
  }

  /** Benchmark WebGPU then WebGL2; adopt whichever clearly beats the CPU Worker. */
  private async tryUpgrade() {
    if (!this.running || this.upgraded) return;
    const target = Math.max(this.workerPps, 1) * UPGRADE_MARGIN;
    const GPU = "WebGPU (compute shader)";
    const GL = "WebGL2 (GPGPU)";

    try {                                                 // ── WebGPU ──
      const gpu = new Bb84Gpu();
      if (await gpu.init()) {
        const r = await gpu.runRound(this.cfg);           // one benchmark round
        if (r.pulsesPerSec >= target) {
          this.record({ tier: GPU, pulsesPerSec: r.pulsesPerSec, adopted: true });
          this.adoptGpu(gpu); return;
        }
        this.record({ tier: GPU, pulsesPerSec: r.pulsesPerSec, adopted: false });
        console.info(`[bb84] WebGPU ${fmt(r.pulsesPerSec)} ≤ Worker ${fmt(this.workerPps)} — keeping Worker`);
        gpu.dispose();
      } else {
        // init() returning false is "this browser has no WebGPU", which is a
        // different fact from "the shader threw" and must not read the same.
        this.record({ tier: GPU, pulsesPerSec: null, adopted: false,
                      error: "not available in this browser" });
      }
    } catch (e) {
      this.record({ tier: GPU, pulsesPerSec: null, adopted: false, error: String(e) });
      console.warn("[bb84] WebGPU init/bench failed — investigate before relying on fallback:", e);
    }

    try {                                                 // ── WebGL2 GPGPU ──
      const gl = new Bb84Gl();
      if (gl.init()) {
        const r = gl.runRound(this.cfg);                  // one benchmark round
        if (r.pulsesPerSec >= target) {
          this.record({ tier: GL, pulsesPerSec: r.pulsesPerSec, adopted: true });
          this.adoptGl(gl); return;
        }
        this.record({ tier: GL, pulsesPerSec: r.pulsesPerSec, adopted: false });
        console.info(`[bb84] WebGL ${fmt(r.pulsesPerSec)} ≤ Worker ${fmt(this.workerPps)} — keeping Worker`);
        gl.dispose();
      } else {
        this.record({ tier: GL, pulsesPerSec: null, adopted: false,
                      error: "not available in this browser" });
      }
    } catch (e) {
      this.record({ tier: GL, pulsesPerSec: null, adopted: false, error: String(e) });
      console.warn("[bb84] WebGL init/bench failed — investigate before relying on fallback:", e);
    }
    // else: keep the CPU Worker (already running)
  }

  /** Attach the selection record to every update, so the page can show it. */
  private emit(u: Omit<Bb84Update, "tierTrials" | "workerPulsesPerSec">) {
    this.onUpdate({ ...u, tierTrials: [...this.trials],
                    workerPulsesPerSec: this.workerPps || null });
  }

  /**
   * A tier that was adopted and then threw mid-run is no longer adopted.
   *
   * The revert path set `upgraded = false` and restarted the CPU worker but
   * left the trial record saying `adopted: true`, so the page rendered
   * "WebGPU (compute shader) 100.0M/s -- adopted" in green next to a badge
   * reading "Worker (CPU)", and the export said the same. `tryUpgrade()` is
   * scheduled once and never re-runs, so that contradiction was permanent for
   * the page load. Precisely the defect this record was added to prevent, with
   * the sign flipped and a citable artefact attached to it.
   */
  private revertTier(tier: string, e: unknown) {
    for (const t of this.trials) {
      if (t.tier === tier && t.adopted) {
        t.adopted = false;
        t.error = `adopted, then failed mid-run and reverted to the CPU worker: ${String(e)}`;
      }
    }
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
      this.emit({ ...r, engine });
    } catch (e) {
      console.warn("[bb84] WebGPU runRound failed — reverting to Worker:", e);
      this.revertTier("WebGPU (compute shader)", e);
      this.gpu?.dispose(); this.gpu = null; this.upgraded = false; this.startWorker(); return;
    }
    if (this.running) this.gpuTimer = window.setTimeout(() => this.gpuLoop(engine), 250);
  }

  private glLoop(engine: string) {
    if (!this.running || !this.gl) return;
    try {
      const r = this.gl.runRound(this.cfg);
      this.emit({ ...r, engine });
    } catch (e) {
      console.warn("[bb84] WebGL runRound failed — reverting to Worker:", e);
      this.revertTier("WebGL2 (GPGPU)", e);
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
        this.emit({ qber: m.qber, pool_size: m.pool_size, frames: m.frames,
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
    // Reset the tier state, so a later start() benchmarks again instead of
    // reporting a stale verdict. Without this, stop() left `upgraded = true`
    // while disposing nothing, and the restart ran the CPU worker while the
    // panel still said "WebGPU -- adopted". Not reachable from the page today,
    // which builds a fresh engine per mount, but this is a public method and
    // the failure is silent.
    this.upgraded = false;
    this.trials = [];
    this.gpu?.dispose(); this.gpu = null;
    this.gl?.dispose(); this.gl = null;
  }

  dispose() {
    this.stop();
    this.gpu?.dispose(); this.gpu = null;
    this.gl?.dispose(); this.gl = null;
  }
}

const fmt = (p: number) => `${(p / 1e6).toFixed(0)}M/s`;
