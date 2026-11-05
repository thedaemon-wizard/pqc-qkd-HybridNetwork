import { useEffect, useMemo, useRef, useState } from "react";
import { colors } from "../lib/commonStyles";
import { usePrefersReducedMotion } from "../lib/layout";
import {
  PLAY_SHARE, STEP_MIN_PLAY_MS, SWEEP_MIN_DWELL_MS,
  packetPose, relayProgress, stepAt, tickWindows,
} from "../lib/sim/protocolLab/playback";
import type { TopologyPreset } from "../lib/sim/protocolLab/publishedNetworks";
import { linksAlong } from "../lib/sim/protocolLab/view";
import type { ProtocolLabState } from "../lib/sim/protocolLabSim";
import RunStatusStrip from "./RunStatusStrip";
import TopologyPresetSvg from "./TopologyPresetSvg";

/** How long the route just left stays drawn after a re-route. */
const PREVIOUS_ROUTE_MS = 2500;
/** Below this time per hop a moving caption cannot be read, so it is left out. */
const CAPTION_MIN_HOP_MS = 300;

interface View { stepIndex: number | null; hop: number | null; atNode: string | null; arrived: boolean }
const AT_REST: View = { stepIndex: null, hop: null, atNode: null, arrived: false };

/**
 * The topology and the status strip, played back tick by tick.
 *
 * The engine runs a tick in one step and records what it did; this draws that
 * record over the tick's dwell, so what moves on screen is always something
 * that happened. The key's position changes every frame and is set on the
 * element directly, so React re-renders only when a stage or a hop changes.
 * With "reduce motion" asked for, nothing moves and each tick's outcome shows
 * at once. The drawing's time is not a latency.
 */
export default function LiveTopology({ preset, state, compact, scaleBits }: {
  preset: TopologyPreset;
  state: ProtocolLabState;
  compact: boolean;
  scaleBits: number | null;
}) {
  const reduced = usePrefersReducedMotion();
  const packet = useRef<SVGGElement>(null);
  const [view, setView] = useState<View>(AT_REST);

  // Read when a tick starts or a frame runs, without restarting the play.
  const latest = useRef(state);
  latest.current = state;

  const trace = state.last_tick;
  const tickKey = trace ? `${state.preset_id}:${state.scenario_id ?? ""}:${trace.tick}` : null;
  useEffect(() => {
    const g = packet.current;
    const hide = () => g?.setAttribute("visibility", "hidden");
    setView(AT_REST);
    hide();
    if (!trace || reduced) return undefined;
    const now = latest.current;
    const play = Math.max(now.nominal_dwell_ms * PLAY_SHARE, now.status === "running" ? 0 : STEP_MIN_PLAY_MS);
    const sweep = play >= SWEEP_MIN_DWELL_MS;
    const windows = tickWindows(trace);
    const started = performance.now();
    let raf = 0;
    let shown = AT_REST;
    const frame = (t: number) => {
      const p = Math.max(0, Math.min(1, (t - started) / play));
      // A failure injected while the key is crossing stops the drawing of it:
      // the engine has already moved on from that route.
      const broken = latest.current.links.some((l) => l.down && trace.relay?.linkIds.includes(l.id));
      const u = broken ? null : relayProgress(trace, windows, p, sweep);
      const pose = u === null ? null : packetPose(preset, trace, u);
      if (g) {
        if (pose) {
          g.setAttribute("transform", `translate(${pose.x.toFixed(1)} ${pose.y.toFixed(1)})`);
          g.setAttribute("visibility", "visible");
        } else {
          hide();
        }
      }
      const next: View = {
        stepIndex: sweep ? stepAt(windows, p) : null,
        hop: pose?.hop ?? null, atNode: pose?.atNode ?? null, arrived: pose?.arrived ?? false,
      };
      if (next.stepIndex !== shown.stepIndex || next.hop !== shown.hop
          || next.atNode !== shown.atNode || next.arrived !== shown.arrived) {
        shown = next;
        setView(next);
      }
      if (p < 1) raf = requestAnimationFrame(frame);
    };
    raf = requestAnimationFrame(frame);
    return () => cancelAnimationFrame(raf);
    // `trace` changes with tickKey; `preset` with the id inside it.
  }, [tickKey, reduced]); // eslint-disable-line react-hooks/exhaustive-deps

  // The route just left, for a moment after a re-route.
  const [leftBehind, setLeftBehind] = useState<string[]>([]);
  const change = state.reroutes[state.reroutes.length - 1];
  const changeKey = change ? `${change.t_s}:${change.to?.join(">") ?? ""}:${state.reroutes.length}` : null;
  useEffect(() => {
    if (!change?.from) { setLeftBehind([]); return undefined; }
    setLeftBehind(linksAlong(preset, change.from));
    const timer = window.setTimeout(() => setLeftBehind([]), PREVIOUS_ROUTE_MS);
    return () => window.clearTimeout(timer);
  }, [changeKey]); // eslint-disable-line react-hooks/exhaustive-deps

  const hopMs = useMemo(() => {
    const hops = trace?.relay ? trace.relay.nodes.length - 1 : 0;
    return hops > 0 ? (state.nominal_dwell_ms * PLAY_SHARE) / hops : 0;
  }, [trace, state.nominal_dwell_ms]);
  const packetLabel = view.hop === null ? null
    : view.atNode ? "key in the clear"
    : view.arrived ? "key recovered"
    : hopMs >= CAPTION_MIN_HOP_MS || state.status !== "running" ? `key ⊕ pad ${view.hop + 1}` : null;

  return (
    <>
      <TopologyPresetSvg preset={preset} links={state.links} route={state.route} downNodes={state.down_nodes}
                         accounting={state.accounting} scaleBits={scaleBits} compact={compact}
                         demand={{ from: state.demand.from, to: state.demand.to }}
                         previousLinks={leftBehind} atNode={view.atNode} arrived={view.arrived}
                         noRoute={state.route === null && state.last_tick !== null}
                         packetRef={packet} packetLabel={packetLabel} />
      <div style={{ display: "flex", gap: 12, flexWrap: "wrap", fontSize: 11, color: colors.textMute, marginTop: 4 }}>
        <span><Dot color={colors.accent} /> key crossing a link under that hop's pad</span>
        <span><Dot color={colors.warn} /> key in the clear at a trusted node</span>
        <span style={{ color: colors.success }}>green line: active route</span>
        <span style={{ color: colors.warn }}>amber dashes: route just left</span>
        <span style={{ color: colors.danger }}>red dashes: down</span>
        {!compact && <span style={{ color: colors.qkd }}>bar under a caption: that link's key store</span>}
        <span>green box: demand endpoints</span>
      </div>
      {compact && (
        <div style={{ fontSize: 11, color: colors.textMute, marginTop: 4 }}>
          Link lengths and losses do not fit at this width: they are in "Links as published" below.
        </div>
      )}
      <RunStatusStrip state={state} stepIndex={view.stepIndex} routeJustChanged={leftBehind.length > 0} />
    </>
  );
}

function Dot({ color }: { color: string }) {
  return <span style={{ display: "inline-block", width: 9, height: 9, borderRadius: "50%", background: color, verticalAlign: "-1px" }} />;
}
