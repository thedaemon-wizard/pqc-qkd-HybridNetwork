/**
 * Failure cascade timeline.
 *
 * Renders the 0-720s cascade described in arXiv:2604.05599, in the
 * "Fail-Safe Mechanism" subsection of Implementation: a component stops no
 * earlier than 60s after the previous layer fails and no later than 180s, so
 * loss of the QKD plane reaches the data path in 240-720s. Test 5 (Simulated
 * QKD malfunction) is the paper's empirical check of it, and its stages are
 * the markers. NOT Table 1, which gives packet and byte budgets and says
 * nothing about timing.
 *
 * Shown when a layer failure has been injected. The head moves along the
 * timeline while the simulation runs; events flip from "pending" to "fired"
 * as the head crosses them.
 *
 * ONE clock. The head and the markers both read PaperSim's cascade clock
 * (`failure.elapsed_s`), which advances only while the simulation is running.
 * They used to run on two: the head on this component's own ticker, the
 * markers on `Date.now() >= triggered_at` recomputed in every snapshot. First
 * the head walked on while paused and passed markers that stayed grey
 * (measured on the deployed build: status paused, t = 257.4s, the 180s and
 * 240s markers still dashed). Gating the ticker fixed that direction and
 * reversed it: a Step or a hop-slider change after a paused wait re-emitted
 * the snapshot and flipped markers to fired while the head stayed frozen.
 * Two clocks cannot be kept in step by gating one of them.
 */
import Panel from "./Panel";
import { colors } from "../lib/commonStyles";

export interface CascadeEvent {
  t_offset_s: number;
  layer: string;
  description: string;
  /** Wall-clock epoch seconds at which the cascade clock reached it, or null. */
  triggered_at: number | null;
  fired: boolean;
}

export interface FailureCascadeProps {
  activeLayer: string | null;
  startedAt: number | null;       // epoch seconds
  /** The simulator's cascade clock: running seconds since the injection. */
  elapsedS: number;
  events: CascadeEvent[];
  /** Simulation run state, shown with the head so a frozen head reads as
   *  paused rather than as stuck. */
  status: "idle" | "running" | "paused" | "stepped";
}

export default function FailureCascadeTimeline({
  activeLayer, startedAt, elapsedS, events, status,
}: FailureCascadeProps) {
  const max = 720;
  const W = 920, H = 130;
  const padL = 80, padR = 30, padT = 30, padB = 30;
  const innerW = W - padL - padR;
  const tElapsed = startedAt ? Math.min(max, elapsedS) : 0;
  const headX = padL + (tElapsed / max) * innerW;

  // The paper has no Roman-numeral headings: they are Arabic, and the 240-720 s
  // cascade is in 4.3 Fail-Safe Mechanism. This Panel title cited the sixth
  // section -- which is Security Evaluation and contains no timing at all --
  // while lines 4-9 of this very file already named the right one. The string a
  // user sees and the comment explaining it disagreed, and only the comment was
  // ever read.
  return (
    <Panel title="Failure Cascade Timeline (0-720 s, arXiv:2604.05599, 4.3 Fail-Safe Mechanism)">
      <svg viewBox={`0 0 ${W} ${H}`} style={{ width: "100%" }}>
        {/* Axis */}
        <line x1={padL} y1={H - padB} x2={W - padR} y2={H - padB}
              stroke={colors.borderLt} />
        {[0, 120, 240, 360, 480, 600, 720].map((t) => {
          const x = padL + (t / max) * innerW;
          return (
            <g key={t}>
              <line x1={x} y1={H - padB} x2={x} y2={H - padB + 4}
                    stroke={colors.textMute} />
              <text x={x} y={H - padB + 16} fill={colors.textMute}
                    fontSize={9} textAnchor="middle">{t}s</text>
            </g>
          );
        })}
        <text x={20} y={H / 2 + 4} fill={colors.textSec} fontSize={11}>
          {activeLayer ? `↓ ${activeLayer}` : "idle"}
        </text>

        {/* Events */}
        {events.map((ev, i) => {
          const x = padL + (ev.t_offset_s / max) * innerW;
          const c = ev.fired ? colors.danger : colors.textMute;
          // Anchor labels near the right edge to "end" so they never clip the
          // viewBox; stagger vertically for tightly-spaced events.
          const nearRight = x > W - padR - 30;
          const stagger = i % 2 === 0 ? 2 : 12;
          return (
            <g key={i} transform={`translate(${x}, ${padT})`}>
              <line x1={0} y1={4} x2={0} y2={H - padT - padB}
                    stroke={c} strokeDasharray={ev.fired ? "0" : "2 3"} />
              <circle cx={0} cy={H - padT - padB} r={4} fill={c} />
              <text x={nearRight ? -4 : 4} y={stagger} fill={c} fontSize={9}
                    textAnchor={nearRight ? "end" : "start"}>{ev.t_offset_s}s</text>
              <title>{`${ev.layer}: ${ev.description}`}</title>
            </g>
          );
        })}

        {/* Current head */}
        {startedAt && (
          <g>
            <line x1={headX} y1={padT} x2={headX} y2={H - padB}
                  stroke={colors.warn} strokeWidth={2} />
            <text x={headX + 4} y={padT + 12} fill={colors.warn} fontSize={10}>
              t = {tElapsed.toFixed(1)}s{status === "running" ? "" : ` (${status})`}
            </text>
          </g>
        )}
      </svg>
      {!activeLayer && (
        <p style={{ color: colors.textMute, fontSize: 11, margin: "4px 8px" }}>
          No layer failure injected. Use the buttons above to start a cascade.
        </p>
      )}
    </Panel>
  );
}
