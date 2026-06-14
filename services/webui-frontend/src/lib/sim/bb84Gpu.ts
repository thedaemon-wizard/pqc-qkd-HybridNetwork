/**
 * BB84 Monte-Carlo on WebGPU (Round 5) — optional GPU accelerator for the
 * per-pulse simulation. A WGSL compute shader runs millions of pulses in
 * parallel, accumulating sifted/error counts with atomicAdd. Falls back to the
 * CPU Web Worker (bb84.worker.ts) when WebGPU is unavailable. Per the
 * diagnose-before-fallback protocol, init() distinguishes "no GPU" (expected →
 * caller uses the Worker) from an implementation error (thrown → investigate).
 */
export interface Bb84Cfg {
  etaTotal: number; eD: number; Y0: number;
  eveOn: boolean; eveProb: number; pulsesPerRound: number;
}
export interface RoundResult {
  qber: number; pool_size: number; pulsesPerSec: number;
  frames: { i: number; alice_bit: number; alice_basis: number;
            bob_basis: number; bob_bit: number; basis_match: boolean }[];
}

const WGSL = /* wgsl */ `
struct Params {
  etaTotal : f32,
  eD       : f32,
  Y0       : f32,
  eveProb  : f32,        // 0 when Eve is off
  pulsesPerThread : u32,
  seed     : u32,
};
@group(0) @binding(0) var<uniform> P : Params;
@group(0) @binding(1) var<storage, read_write> counters : array<atomic<u32>, 2>; // [sifted, errors]

// xorshift32 PRNG state per invocation
fn nextu(state: ptr<function, u32>) -> u32 {
  var x = *state;
  x = x ^ (x << 13u);
  x = x ^ (x >> 17u);
  x = x ^ (x << 5u);
  *state = x;
  return x;
}
fn nextf(state: ptr<function, u32>) -> f32 {
  return f32(nextu(state)) / 4294967296.0;
}
fn nextbit(state: ptr<function, u32>) -> u32 {
  return select(0u, 1u, nextf(state) < 0.5);
}

@compute @workgroup_size(64)
fn main(@builtin(global_invocation_id) gid : vec3<u32>) {
  var state : u32 = P.seed ^ (gid.x * 2654435761u + 1u);
  if (state == 0u) { state = 1u; }
  let detect = P.etaTotal + P.Y0;
  var sifted : u32 = 0u;
  var errors : u32 = 0u;
  for (var i : u32 = 0u; i < P.pulsesPerThread; i = i + 1u) {
    if (nextf(&state) >= detect) { continue; }
    let aBit = nextbit(&state);
    let aBasis = nextbit(&state);
    var carriedBit = aBit;
    var carriedBasis = aBasis;
    if (P.eveProb > 0.0 && nextf(&state) < P.eveProb) {
      let eBasis = nextbit(&state);
      var eBit = aBit;
      if (eBasis != aBasis) { eBit = nextbit(&state); }
      carriedBit = eBit;
      carriedBasis = eBasis;
    }
    let bBasis = nextbit(&state);
    var bBit : u32;
    if (bBasis == carriedBasis) {
      if (nextf(&state) < P.eD) { bBit = carriedBit ^ 1u; } else { bBit = carriedBit; }
    } else {
      bBit = nextbit(&state);
    }
    if (aBasis == bBasis) {
      sifted = sifted + 1u;
      if (aBit != bBit) { errors = errors + 1u; }
    }
  }
  atomicAdd(&counters[0], sifted);
  atomicAdd(&counters[1], errors);
}
`;

const THREADS = 16384;          // 256 workgroups × 64 — millions of pulses/dispatch

export class Bb84Gpu {
  private device: GPUDevice | null = null;
  private pipeline: GPUComputePipeline | null = null;
  private paramBuf!: GPUBuffer;
  private countBuf!: GPUBuffer;
  private readBuf!: GPUBuffer;
  private bind!: GPUBindGroup;
  private pool = 0;

  /** Returns true if WebGPU initialised; false if unavailable (use the Worker).
   *  Throws on an actual implementation error (per diagnose-before-fallback). */
  async init(): Promise<boolean> {
    const gpu = (navigator as any).gpu as GPU | undefined;
    if (!gpu) return false;                       // capability miss → caller uses Worker
    const adapter = await gpu.requestAdapter();
    if (!adapter) return false;
    this.device = await adapter.requestDevice();  // errors here propagate (real failure)
    const mod = this.device.createShaderModule({ code: WGSL });
    this.pipeline = this.device.createComputePipeline({
      layout: "auto", compute: { module: mod, entryPoint: "main" } });
    this.paramBuf = this.device.createBuffer({
      size: 24, usage: GPUBufferUsage.UNIFORM | GPUBufferUsage.COPY_DST });
    this.countBuf = this.device.createBuffer({
      size: 8, usage: GPUBufferUsage.STORAGE | GPUBufferUsage.COPY_SRC | GPUBufferUsage.COPY_DST });
    this.readBuf = this.device.createBuffer({
      size: 8, usage: GPUBufferUsage.MAP_READ | GPUBufferUsage.COPY_DST });
    this.bind = this.device.createBindGroup({
      layout: this.pipeline.getBindGroupLayout(0),
      entries: [
        { binding: 0, resource: { buffer: this.paramBuf } },
        { binding: 1, resource: { buffer: this.countBuf } },
      ] });
    return true;
  }

  async runRound(cfg: Bb84Cfg): Promise<RoundResult> {
    const d = this.device!;
    const pulsesPerThread = Math.max(1, Math.floor(cfg.pulsesPerRound / THREADS));
    const totalPulses = pulsesPerThread * THREADS;
    const seed = (Math.random() * 0xffffffff) >>> 0;
    // uniforms: 3×f32 + f32 + u32 + u32
    const ab = new ArrayBuffer(24);
    new Float32Array(ab, 0, 4).set([cfg.etaTotal, cfg.eD, cfg.Y0, cfg.eveOn ? cfg.eveProb : 0]);
    new Uint32Array(ab, 16, 2).set([pulsesPerThread, seed]);
    d.queue.writeBuffer(this.paramBuf, 0, ab);
    d.queue.writeBuffer(this.countBuf, 0, new Uint32Array([0, 0]));

    const t0 = performance.now();
    const enc = d.createCommandEncoder();
    const pass = enc.beginComputePass();
    pass.setPipeline(this.pipeline!);
    pass.setBindGroup(0, this.bind);
    pass.dispatchWorkgroups(THREADS / 64);
    pass.end();
    enc.copyBufferToBuffer(this.countBuf, 0, this.readBuf, 0, 8);
    d.queue.submit([enc.finish()]);
    await this.readBuf.mapAsync(GPUMapMode.READ);
    const [sifted, errors] = new Uint32Array(this.readBuf.getMappedRange().slice(0));
    this.readBuf.unmap();
    const dt = Math.max(performance.now() - t0, 1e-3);

    const qber = sifted > 0 ? errors / sifted : 0;
    this.pool = Math.max(0, Math.min(4096,
      this.pool + Math.floor(sifted * (1 - 2 * qber) * 0.25) - 64));
    return {
      qber, pool_size: this.pool,
      pulsesPerSec: Math.round(totalPulses / (dt / 1000)),
      frames: cpuSampleFrames(cfg, 16),
    };
  }

  dispose() { this.device?.destroy?.(); this.device = null; }
}

/** Small CPU helper to produce display sample frames (GPU only returns counts). */
function cpuSampleFrames(cfg: Bb84Cfg, n: number) {
  const frames = [];
  const bit = () => (Math.random() < 0.5 ? 0 : 1);
  let i = 0, guard = 0;
  while (frames.length < n && guard++ < n * 50) {
    i++;
    if (Math.random() >= cfg.etaTotal + cfg.Y0) continue;
    const aBit = bit(), aBasis = bit();
    let cBit = aBit, cBasis = aBasis;
    if (cfg.eveOn && Math.random() < cfg.eveProb) {
      const eBasis = bit(); cBit = eBasis === aBasis ? aBit : bit(); cBasis = eBasis;
    }
    const bBasis = bit();
    const bBit = bBasis === cBasis ? (Math.random() < cfg.eD ? cBit ^ 1 : cBit) : bit();
    frames.push({ i, alice_bit: aBit, alice_basis: aBasis,
      bob_basis: bBasis, bob_bit: bBit, basis_match: aBasis === bBasis });
  }
  return frames;
}
