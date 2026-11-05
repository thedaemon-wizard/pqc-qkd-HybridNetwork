/**
 * How /protocol-lab plays one tick back: which of its parts is lit and where the
 * key is on its route, at each moment of the tick's dwell. Pure, so it can be
 * tested without a DOM or a clock.
 *
 * This is a drawing of a record, not a model. The engine runs a tick in one
 * step and says what it did (TickTrace); nothing here feeds back into it, and
 * the time a packet takes to cross a link on screen is not a latency.
 */
import type { TopologyPreset } from "./publishedNetworks";
import type { TickTrace } from "../protocolLabSim";

/**
 * Below this dwell a part of the tick would be lit too briefly to read, and the
 * strip only flickers, so a fast run lights none and gives the whole dwell to
 * the key.
 */
export const SWEEP_MIN_DWELL_MS = 600;
/**
 * A Step is one tick someone asked to look at, so it plays at least this long
 * at any speed.
 */
export const STEP_MIN_PLAY_MS = 1200;
/** Of a hop's time, the part spent crossing the link; the rest is at the next node. */
export const TRAVEL_SHARE = 0.76;
/** Of the dwell, the part played, so a tick has ended before the next begins. */
export const PLAY_SHARE = 0.92;

/**
 * How to play a tick, or null when it should not move at all: with reduced
 * motion asked for, no frame loop runs and the outcome shows at once.
 */
export function playbackPlan(dwellMs: number, running: boolean, reducedMotion: boolean): { playMs: number; sweep: boolean } | null {
  if (reducedMotion) return null;
  const playMs = Math.max(dwellMs * PLAY_SHARE, running ? 0 : STEP_MIN_PLAY_MS);
  return { playMs, sweep: playMs >= SWEEP_MIN_DWELL_MS };
}

export interface StepWindow { index: number; start: number; end: number }

/** Each part's share of a tick: equal, except that relaying takes one share per hop. */
export function tickWindows(trace: TickTrace): StepWindow[] {
  const hops = trace.relay ? Math.max(1, trace.relay.nodes.length - 1) : 1;
  const weights = trace.steps.map((s) => (s.id === "relay" && trace.relay ? hops + 1 : 1));
  const total = weights.reduce((a, b) => a + b, 0);
  let at = 0;
  return weights.map((w, index) => {
    const start = at / total;
    at += w;
    return { index, start, end: at / total };
  });
}

/** The part lit at progress `p` of the tick (0..1), or null once it has played. */
export function stepAt(windows: readonly StepWindow[], p: number): number | null {
  if (p >= 1) return null;
  return windows.find((w) => p < w.end)?.index ?? null;
}

export interface PacketPose {
  x: number;
  y: number;
  /** Zero-based hop the key is on. */
  hop: number;
  /** The trusted node holding the key in the clear right now, if any. */
  atNode: string | null;
  /** The key has crossed the last hop: the far end has taken the last pad off. */
  arrived: boolean;
}

const ease = (u: number) => (u < 0.5 ? 2 * u * u : 1 - (-2 * u + 2) ** 2 / 2);

/**
 * Where the key is at progress `u` (0..1) through the relaying. It crosses each
 * hop under that hop's pad, and between hops it stays a moment at the trusted
 * node, which takes one pad off and puts the next one on: that is where the
 * key is in the clear.
 */
export function packetPose(preset: TopologyPreset, trace: TickTrace, u: number): PacketPose | null {
  const relay = trace.relay;
  if (!relay || u < 0 || u >= 1 || relay.nodes.length < 2) return null;
  const hops = relay.nodes.length - 1;
  const along = u * hops;
  const hop = Math.min(hops - 1, Math.floor(along));
  const f = along - hop;
  const a = preset.nodes.find((n) => n.id === relay.nodes[hop]);
  const b = preset.nodes.find((n) => n.id === relay.nodes[hop + 1]);
  if (!a || !b) return null;
  const crossing = f < TRAVEL_SHARE;
  const t = crossing ? ease(f / TRAVEL_SHARE) : 1;
  return {
    x: a.x + (b.x - a.x) * t,
    y: a.y + (b.y - a.y) * t,
    hop,
    atNode: !crossing && hop < hops - 1 ? relay.nodes[hop + 1] : null,
    arrived: !crossing && hop === hops - 1,
  };
}

/** Progress through the relaying at progress `p` of the tick, or null outside it. */
export function relayProgress(trace: TickTrace, windows: readonly StepWindow[], p: number, sweep: boolean): number | null {
  if (!trace.relay || p >= 1) return null;
  if (!sweep) return p;
  const i = trace.steps.findIndex((s) => s.id === "relay");
  const w = windows[i];
  if (!w || p < w.start || p >= w.end) return null;
  return (p - w.start) / (w.end - w.start);
}
