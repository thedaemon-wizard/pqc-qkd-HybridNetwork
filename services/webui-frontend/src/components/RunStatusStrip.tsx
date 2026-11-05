import type { CSSProperties } from "react";
import { colors } from "../lib/commonStyles";
import {
  TICK_PIPELINE, type ProtocolLabState, type StepOutcome, type TickRec,
} from "../lib/sim/protocolLabSim";

/**
 * The run's state as it changes: the run itself, what the latest tick did part
 * by part, the route, and the latest ticks as one bar. Words and marks carry the
 * meaning as well as the colours, so nothing rests on telling them apart.
 */
const MARK: Record<StepOutcome, string> = { ok: "✓", wait: "…", fail: "✕", idle: "–" };
const WORD: Record<StepOutcome, string> = { ok: "done", wait: "waiting", fail: "failed", idle: "nothing due" };
const TONE: Record<StepOutcome, string> = {
  ok: colors.success, wait: colors.warn, fail: colors.danger, idle: colors.textMute,
};

const RUN_STATES = ["idle", "running", "paused", "stepped"] as const;

/**
 * Three edges by name, not `border` beside `borderLeft`: React warns when the
 * shorthand changes under a longhand, because the browser would reset the left edge.
 */
export const PART_EDGES = (colour: string): CSSProperties => ({
  borderTop: `1px solid ${colour}`, borderRight: `1px solid ${colour}`, borderBottom: `1px solid ${colour}`,
});

/** One line on where the service stands after the latest tick. */
export function serviceState(s: ProtocolLabState): { label: string; outcome: StepOutcome } {
  const steps = s.last_tick?.steps;
  if (!steps) return { label: "not started", outcome: "idle" };
  const of = (id: string) => steps.find((x) => x.id === id);
  if (of("route")?.outcome === "fail") return { label: "no route", outcome: "fail" };
  if (of("relay")?.outcome === "wait") return { label: "waiting for key", outcome: "wait" };
  const d = of("deliver");
  if (d?.outcome === "fail") return { label: "refused", outcome: "fail" };
  if (d?.outcome === "wait") return { label: "partly served", outcome: "wait" };
  if (d?.outcome === "ok") return { label: "delivering", outcome: "ok" };
  if (s.accounting === "route-only") return { label: "route held, nothing counted", outcome: "ok" };
  return { label: "route held, nothing due", outcome: "idle" };
}

/** A tick's colour in the history bar, and what the caption says it means. */
export function tickTone(h: TickRec): string {
  if (h.route === "" || (h.unmet_bits > 0 && h.delivered_bits === 0)) return colors.danger;
  if (h.unmet_bits > 0) return colors.warn;
  if (h.delivered_bits > 0) return colors.success;
  return colors.borderLt;
}

const chip = (on: boolean, tone: string): CSSProperties => ({
  padding: "2px 8px", borderRadius: 10, fontSize: 11, whiteSpace: "nowrap",
  border: `1px solid ${on ? tone : colors.border}`,
  background: on ? colors.active : "transparent",
  color: on ? colors.textPri : colors.textMute,
  fontWeight: on ? 700 : 400,
});

function StatusHistory({ history }: { history: TickRec[] }) {
  // Room for a minute of ticks at first, so the first ticks are not one solid
  // block; after that the bar compresses to hold what the history holds, which
  // is a rolling window, so the caption says "latest", not "every".
  const n = Math.max(60, history.length);
  const changes = history.flatMap((h, i) => (i > 0 && h.route !== history[i - 1].route ? [i] : []));
  return (
    <div style={{ marginTop: 8 }}>
      <svg viewBox={`0 0 ${n} 10`} preserveAspectRatio="none" role="img"
           aria-label={`The latest ${history.length} tick(s), with ${changes.length} route change(s)`}
           style={{ display: "block", width: "100%", height: 14, background: colors.panelDark, borderRadius: 3 }}>
        {history.map((h, i) => <rect key={h.tick} x={i} y={0} width={1} height={10} fill={tickTone(h)} />)}
        {changes.map((i) => <rect key={i} x={i} y={0} width={Math.max(0.3, n / 400)} height={10} fill={colors.textPri} />)}
      </svg>
      <div style={{ fontSize: 11, color: colors.textMute, marginTop: 2 }}>
        The latest {history.length} tick(s): green delivered, amber partly served, red refused or no route, grey nothing due; a white mark is a route change.
      </div>
    </div>
  );
}

export default function RunStatusStrip({ state, stepIndex, routeJustChanged }: {
  state: ProtocolLabState;
  /** The part being played back now; null when it has played, or when nothing moves. */
  stepIndex: number | null;
  routeJustChanged: boolean;
}) {
  const pipeline = TICK_PIPELINE[state.accounting];
  const trace = state.last_tick;
  const service = serviceState(state);
  const lastChange = state.reroutes[state.reroutes.length - 1];
  return (
    <div style={{ marginTop: 8, border: `1px solid ${colors.border}`, borderRadius: 8, padding: 8 }}>
      <div style={{ display: "flex", gap: 6, flexWrap: "wrap", alignItems: "center", fontSize: 11, color: colors.textSec }}>
        <span>Run:</span>
        {RUN_STATES.map((r) => <span key={r} style={chip(state.status === r, colors.accent)}>{r}</span>)}
        <span style={{ marginLeft: 8 }}>Service:</span>
        <span style={chip(true, TONE[service.outcome])}>{MARK[service.outcome]} {service.label}</span>
      </div>

      <div style={{ fontSize: 11, color: colors.textSec, marginTop: 8 }}>
        {trace ? `Tick ${trace.tick} (simulated t = ${trace.t_s} s), in order:` : "What a tick does. Press Run or Step to play it:"}
      </div>
      <ol style={{ listStyle: "none", margin: "4px 0 0 0", padding: 0, display: "grid", gap: 6,
                   gridTemplateColumns: "repeat(auto-fit, minmax(130px, 1fr))" }}>
        {pipeline.map((p, i) => {
          const step = trace?.steps[i];
          // While a tick plays, a part shows its outcome once the play reaches it.
          const reached = step !== undefined && (stepIndex === null || i <= stepIndex);
          const lit = stepIndex === i;
          const tone = reached ? TONE[step.outcome] : colors.border;
          return (
            <li key={p.id} aria-current={lit ? "step" : undefined}
                style={{ ...PART_EDGES(lit ? colors.accent : colors.border),
                         borderLeft: `4px solid ${tone}`, borderRadius: 4, padding: "4px 6px", minWidth: 0,
                         background: lit ? colors.active : "transparent",
                         transition: "background 0.12s, border-color 0.12s" }}>
              <div style={{ fontSize: 11, color: colors.textPri, fontWeight: 600 }}>
                {i + 1}. {p.label}
              </div>
              <div style={{ fontSize: 11, color: reached ? tone : colors.textMute, overflowWrap: "anywhere" }}>
                {reached ? <>{MARK[step.outcome]} {WORD[step.outcome]}</> : " "}
              </div>
              <div style={{ fontSize: 11, color: colors.textMute, overflowWrap: "anywhere",
                            visibility: reached ? "visible" : "hidden" }}>
                {step?.detail ?? " "}
              </div>
            </li>
          );
        })}
      </ol>

      {/* One status line, and no tick number in it, so it speaks when the state
          changes and not on every tick. */}
      <div role="status" style={{ fontSize: 12, marginTop: 8, padding: "2px 6px", borderRadius: 4, overflowWrap: "anywhere",
                                  color: state.route ? colors.textPri : colors.danger,
                                  background: routeJustChanged ? colors.active : "transparent",
                                  transition: "background 0.2s" }}>
        Run {state.status}, service {service.label}. Route: {state.route ? state.route.nodes.join(" > ") : `none (${state.route_none ?? "not chosen yet"})`}
        {lastChange && lastChange.reason !== "start" && (
          <span style={{ color: colors.textSec }}>
            {" "}; last change at t = {lastChange.t_s} s ({lastChange.reason})
          </span>
        )}
      </div>

      <StatusHistory history={state.history} />
    </div>
  );
}
