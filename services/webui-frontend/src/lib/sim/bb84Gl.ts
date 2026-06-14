/**
 * BB84 Monte-Carlo on WebGL2 (Round 5b) — a GPU-compute tier for browsers that
 * have WebGL2 but NOT WebGPU (e.g. Safari, older Chrome/Firefox). Uses the
 * standard WebGL2 GPGPU pattern: draw N GL_POINTS whose vertex shader simulates
 * one pulse each (PRNG seeded by gl_VertexID), scatter them across a float
 * accumulation framebuffer, and let ONE/ONE additive blending sum the
 * (sifted, error) counts in hardware; one readPixels reduces the bins.
 *
 * It is only ADOPTED if it actually beats the CPU Worker (the controller
 * benchmarks it) — so a software rasteriser (SwiftShader) won't be used.
 */
import type { Bb84Cfg, RoundResult } from "./bb84Gpu";

const GRID = 256;                 // 256×256 = 65 536 accumulation bins
const VS = `#version 300 es
uniform uint  uSeed;
uniform float uDetect;            // etaTotal + Y0
uniform float uED;
uniform float uEveProb;           // 0 when Eve off
flat out vec2 vCount;             // (sifted, error)
uint rng(inout uint s){ s ^= s << 13u; s ^= s >> 17u; s ^= s << 5u; return s; }
float rf(inout uint s){ return float(rng(s)) / 4294967296.0; }
uint  rb(inout uint s){ return rf(s) < 0.5 ? 1u : 0u; }
void main() {
  uint s = uSeed ^ (uint(gl_VertexID) * 2654435761u + 1u);
  if (s == 0u) s = 1u;
  float sifted = 0.0; float err = 0.0;
  if (rf(s) < uDetect) {
    uint aBit = rb(s); uint aBasis = rb(s);
    uint cBit = aBit;  uint cBasis = aBasis;
    if (uEveProb > 0.0 && rf(s) < uEveProb) {
      uint eBasis = rb(s);
      uint eBit = eBasis == aBasis ? aBit : rb(s);
      cBit = eBit; cBasis = eBasis;
    }
    uint bBasis = rb(s);
    uint bBit;
    if (bBasis == cBasis) { bBit = rf(s) < uED ? cBit ^ 1u : cBit; }
    else { bBit = rb(s); }
    if (aBasis == bBasis) { sifted = 1.0; if (aBit != bBit) err = 1.0; }
  }
  vCount = vec2(sifted, err);
  uint bin = uint(gl_VertexID) % uint(${GRID * GRID});
  float px = float(bin % uint(${GRID}));
  float py = float(bin / uint(${GRID}));
  vec2 ndc = (vec2(px, py) + 0.5) / float(${GRID}) * 2.0 - 1.0;
  gl_Position = vec4(ndc, 0.0, 1.0);
  gl_PointSize = 1.0;
}`;
const FS = `#version 300 es
precision highp float;
flat in vec2 vCount;
out vec4 outColor;
void main() { outColor = vec4(vCount, 0.0, 0.0); }`;

export class Bb84Gl {
  private gl: WebGL2RenderingContext | null = null;
  private prog: WebGLProgram | null = null;
  private fbo: WebGLFramebuffer | null = null;
  private tex: WebGLTexture | null = null;
  private uSeed!: WebGLUniformLocation | null;
  private uDetect!: WebGLUniformLocation | null;
  private uED!: WebGLUniformLocation | null;
  private uEve!: WebGLUniformLocation | null;
  private readBuf = new Float32Array(GRID * GRID * 4);
  private pool = 0;

  /** Returns true if WebGL2 + float framebuffer initialised; false otherwise. */
  init(): boolean {
    const canvas = document.createElement("canvas");
    canvas.width = GRID; canvas.height = GRID;
    const gl = canvas.getContext("webgl2", { antialias: false, depth: false });
    if (!gl) return false;
    if (!gl.getExtension("EXT_color_buffer_float")) return false;   // need float RTT
    this.gl = gl;
    const vs = compile(gl, gl.VERTEX_SHADER, VS);
    const fs = compile(gl, gl.FRAGMENT_SHADER, FS);
    if (!vs || !fs) return false;
    const prog = gl.createProgram()!;
    gl.attachShader(prog, vs); gl.attachShader(prog, fs); gl.linkProgram(prog);
    if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) {
      // Real implementation error → surface it (diagnose-before-fallback).
      throw new Error("WebGL link failed: " + gl.getProgramInfoLog(prog));
    }
    this.prog = prog;
    this.uSeed = gl.getUniformLocation(prog, "uSeed");
    this.uDetect = gl.getUniformLocation(prog, "uDetect");
    this.uED = gl.getUniformLocation(prog, "uED");
    this.uEve = gl.getUniformLocation(prog, "uEveProb");
    this.tex = gl.createTexture();
    gl.bindTexture(gl.TEXTURE_2D, this.tex);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA32F, GRID, GRID, 0, gl.RGBA, gl.FLOAT, null);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.NEAREST);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.NEAREST);
    this.fbo = gl.createFramebuffer();
    gl.bindFramebuffer(gl.FRAMEBUFFER, this.fbo);
    gl.framebufferTexture2D(gl.FRAMEBUFFER, gl.COLOR_ATTACHMENT0, gl.TEXTURE_2D, this.tex, 0);
    if (gl.checkFramebufferStatus(gl.FRAMEBUFFER) !== gl.FRAMEBUFFER_COMPLETE) return false;
    return true;
  }

  runRound(cfg: Bb84Cfg): RoundResult {
    const gl = this.gl!;
    const t0 = performance.now();
    gl.bindFramebuffer(gl.FRAMEBUFFER, this.fbo);
    gl.viewport(0, 0, GRID, GRID);
    gl.clearColor(0, 0, 0, 0); gl.clear(gl.COLOR_BUFFER_BIT);
    gl.useProgram(this.prog);
    gl.enable(gl.BLEND); gl.blendFunc(gl.ONE, gl.ONE);
    gl.uniform1ui(this.uSeed, (Math.random() * 0xffffffff) >>> 0);
    gl.uniform1f(this.uDetect, cfg.etaTotal + cfg.Y0);
    gl.uniform1f(this.uED, cfg.eD);
    gl.uniform1f(this.uEve, cfg.eveOn ? cfg.eveProb : 0);
    gl.drawArrays(gl.POINTS, 0, cfg.pulsesPerRound);
    gl.disable(gl.BLEND);
    gl.readPixels(0, 0, GRID, GRID, gl.RGBA, gl.FLOAT, this.readBuf);
    let sifted = 0, errors = 0;
    for (let i = 0; i < this.readBuf.length; i += 4) {
      sifted += this.readBuf[i]; errors += this.readBuf[i + 1];
    }
    const dt = Math.max(performance.now() - t0, 1e-3);
    const qber = sifted > 0 ? errors / sifted : 0;
    this.pool = Math.max(0, Math.min(4096,
      this.pool + Math.floor(sifted * (1 - 2 * qber) * 0.25) - 64));
    return {
      qber, pool_size: this.pool,
      pulsesPerSec: Math.round(cfg.pulsesPerRound / (dt / 1000)),
      frames: cpuSampleFrames(cfg, 16),
    };
  }

  dispose() {
    const gl = this.gl; if (!gl) return;
    gl.deleteProgram(this.prog); gl.deleteFramebuffer(this.fbo); gl.deleteTexture(this.tex);
    this.gl = null;
  }
}

function compile(gl: WebGL2RenderingContext, type: number, src: string): WebGLShader | null {
  const sh = gl.createShader(type)!;
  gl.shaderSource(sh, src); gl.compileShader(sh);
  if (!gl.getShaderParameter(sh, gl.COMPILE_STATUS)) {
    throw new Error("WebGL shader compile failed: " + gl.getShaderInfoLog(sh));
  }
  return sh;
}

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
