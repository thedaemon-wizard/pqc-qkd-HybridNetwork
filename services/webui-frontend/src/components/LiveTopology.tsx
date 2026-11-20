import { useEffect, useMemo, useRef, useState } from "react";
import { colors } from "../lib/commonStyles";
import { usePrefersReducedMotion } from "../lib/layout";
import {
  PLAY_SHARE, packetPose, playbackPlan, relayProgress, stepAt, tickWindows,
} from "../lib/sim/protocolLab/playback";
import type { TopologyPreset } from "../lib/sim/protocolLab/publishedNetworks";
import { bandHeight, linksAlong } from "../lib/sim/protocolLab/view";
import { TICK_PIPELINE, type ProtocolLabState } from "../lib/sim/protocolLabSim";
import RunStatusStrip, { serviceState } from "./RunStatusStrip";
import TopologyPresetSvg from "./TopologyPresetSvg";

/** How long the route just left stays drawn after a re-route. */
const PREVIOUS_ROUTE_MS = 2500;
/** Below this time per hop a moving caption cannot be read, so it is left out. */
const CAPTION_MIN_HOP_MS = 300;
/** Said in the band under a network whose accounting moves no key. */
export const ROUTE_ONLY_NOTE = "Route only: no rate is bound to a span, so no key is drawn.";
/**
 * Keeps the drawing and the buttons above it on one screen, as a width so that
 * the drawing keeps its proportions. A height on the SVG itself would go out with
 * every export: serialised and drawn as an image, "vh" means the image's height.
 */
const DRAWING_MAX_VH = 58;

interface View { stepIndex: number | null; hop: number | null; atNode: string | null; arrived: boolean }
const AT_REST: View = { stepIndex: null, hop: null, atNode: null, arrived: false };

/**
 * The band under the network, as lines: what the drawing is, the run's state
 * and the route. Pure, so it can be tested with the step a re-render may still
 * carry from the previous network: a step past this network's pipeline -- the
 * route-only one has a single part -- adds no "now" part. Indexing past the end
 * threw, and the page failed to render when the network was changed while a
 * tick was playing (measured on the deployed build 2026-11-20).
 */
export function topologyBand(preset: TopologyPreset, state: ProtocolLabState, stepIndex: number | null,
                             compact: boolean): string[] {
  const pipeline = TICK_PIPELINE[state.accounting];
  const step = stepIndex === null ? undefined : pipeline[stepIndex];
  const now = step && stepIndex !== null ? `; now ${stepIndex + 1} of ${pipeline.length}, ${step.label}` : "";
  const waitingOn = state.last_tick?.waitingOn ?? null;
  const waiting = waitingOn ? state.links.find((l) => l.id === waitingOn) : undefined;
  // Floor, so a key that is not yet whole never reads as 100 %.
  const waitText = !waitingOn ? ""
    : compact || waiting?.nextKeyFraction == null ? ` on ${waitingOn}`
    : ` on ${waitingOn} (next key ${Math.floor(waiting.nextKeyFraction * 100)} %)`;
  const notes = compact ? "" : [
    state.accounting === "route-only" ? ROUTE_ONLY_NOTE : "",
    preset.drawingNote ?? "",
  ].filter(Boolean).map((n) => ` ${n}`).join("");
  return [
    `Simulation, not the running stack.${notes}`,
    `t = ${state.sim_time_s} s; ${state.status}; ${serviceState(state).label}${waitText}${compact ? "" : now}`,
    ...(compact ? [] : [`Route: ${state.route ? state.route.nodes.join(" > ") : "none"}`]),
  ];
}

/**
 * The topology and the status strip, played back tick by tick.
 *
 * The engine runs a tick in one step and records what it did; this draws that
 * record over the tick's dwell, so what moves on screen is always something
 * that happened. The key's position changes every frame and is set on the
 * element directly, so React re-renders only when a part or a hop changes.
 * With "reduce motion" asked for, nothing moves and each tick's outcome shows
 * at once. Pause stops the drawing where the tick stands: the engine has already
 * finished that tick, so the outcome shows at once there too. The drawing's time
 * is not a latency, and the legend says so.
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
  const frameId = useRef(0);
  const stop = () => {
    cancelAnimationFrame(frameId.current);
    packet.current?.setAttribute("visibility", "hidden");
    setView(AT_REST);
  };
  useEffect(() => {
    stop();
    const plan = trace ? playbackPlan(latest.current.nominal_dwell_ms, latest.current.status === "running", reduced) : null;
    if (!trace || !plan) return undefined;
    const g = packet.current;
    const { playMs, sweep } = plan;
    const windows = tickWindows(trace);
    const started = performance.now();
    let shown = AT_REST;
    const frame = (t: number) => {
      const p = Math.max(0, Math.min(1, (t - started) / playMs));
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
          g.setAttribute("visibility", "hidden");
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
      if (p < 1) frameId.current = requestAnimationFrame(frame);
    };
    frameId.current = requestAnimationFrame(frame);
    return () => cancelAnimationFrame(frameId.current);
    // `trace` changes with tickKey; `preset` with the id inside it.
  }, [tickKey, reduced]); // eslint-disable-line react-hooks/exhaustive-deps

  // Pause freezes the picture. A Step from paused plays its tick, because the
  // status stays "paused" across it and so this does not run.
  useEffect(() => {
    if (state.status === "paused") stop();
  }, [state.status]); // eslint-disable-line react-hooks/exhaustive-deps

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

  const band = topologyBand(preset, state, view.stepIndex, compact);
  // A re-render can still carry the last network's step for a moment after the
  // network changes; past the new pipeline's end it marks nothing.
  const stepShown = view.stepIndex !== null && view.stepIndex < TICK_PIPELINE[state.accounting].length ? view.stepIndex : null;
  const routeOnly = state.accounting === "route-only";
  const hasBars = state.accounting === "keys" || state.accounting === "stores";
  const [W, H] = preset.viewBox;
  const aspect = W / (H + bandHeight(band.length, compact));

  return (
    <>
      <div style={{ maxWidth: `${DRAWING_MAX_VH * aspect}vh`, margin: "0 auto" }}>
        <TopologyPresetSvg preset={preset} links={state.links} route={state.route} downNodes={state.down_nodes}
                           accounting={state.accounting} scaleBits={scaleBits} compact={compact}
                           demand={{ from: state.demand.from, to: state.demand.to }}
                           previousLinks={leftBehind} atNode={view.atNode} arrived={view.arrived}
                           noRoute={state.route === null && state.last_tick !== null}
                           packetRef={packet} packetLabel={packetLabel} band={band}
                           waitingOn={trace?.waitingOn ?? null} />
      </div>
      {preset.drawingNote && (
        <div style={{ fontSize: 12, color: colors.warn, marginTop: 4 }}>{preset.drawingNote}</div>
      )}
      {routeOnly && (
        <div style={{ fontSize: 12, color: colors.warn, marginTop: 4 }}>
          {ROUTE_ONLY_NOTE} Nothing is generated or relayed here; the green line is the route chosen
          from the spans that are up. Inject a failure to see it change.
        </div>
      )}
      <div style={{ display: "flex", gap: 12, flexWrap: "wrap", fontSize: 11, color: colors.textMute, marginTop: 4 }}>
        {/* Only what this accounting draws: under route-only no key moves and no bar is drawn. */}
        {!routeOnly && <span><Dot color={colors.accent} /> key crossing a link under that hop's pad</span>}
        {!routeOnly && <span><Dot color={colors.warn} /> key in the clear at a trusted node</span>}
        <span style={{ color: colors.success }}>green line: active route</span>
        <span style={{ color: colors.warn }}>amber dashes: route just left</span>
        <span style={{ color: colors.danger }}>red dashes: down</span>
        {!compact && hasBars && <span style={{ color: colors.qkd }}>bar under a caption: that link's key store</span>}
        {!compact && state.accounting === "keys" && <span style={{ color: colors.warn }}>amber caption: the hop the relay waits on; its bar is the key it is making</span>}
        <span>green box: demand endpoints</span>
        {!routeOnly && <span>The time a key takes on screen is not a latency.</span>}
      </div>
      {compact && (
        <div style={{ fontSize: 11, color: colors.textMute, marginTop: 4 }}>
          Link lengths and losses do not fit at this width: they are in "Links as published" below.
        </div>
      )}
      <RunStatusStrip state={state} stepIndex={stepShown} routeJustChanged={leftBehind.length > 0} />
    </>
  );
}

function Dot({ color }: { color: string }) {
  return <span style={{ display: "inline-block", width: 9, height: 9, borderRadius: "50%", background: color, verticalAlign: "-1px" }} />;
}
