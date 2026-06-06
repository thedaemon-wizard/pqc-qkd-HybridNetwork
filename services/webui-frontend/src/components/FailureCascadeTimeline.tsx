/**
 * Failure cascade timeline (Phase 14).
 *
 * Renders the 7-stage 0-720s cascade described in arXiv:2604.05599 §IV-B
 * (Table III) when a layer failure has been injected. The current wall-clock
 * head moves along the timeline; events flip from "pending" to "fired" as the
 * head crosses them.
 */
import { useEffect, useState } from "react";
import Panel from "./Panel";
import { colors } from "../lib/commonStyles";

export interface CascadeEvent {
  t_offset_s: number;
  layer: string;
  description: string;
  triggered_at: number | null;
  fired: boolean;
}

export interface FailureCascadeProps {
  activeLayer: string | null;
  startedAt: number | null;       // epoch seconds
  events: CascadeEvent[];
}

export default function FailureCascadeTimeline({
  activeLayer, startedAt, events,
}: FailureCascadeProps) {
  const [now, setNow] = useState<number>(Date.now() / 1000);
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now() / 1000), 500);
    return () => clearInterval(t);
  }, []);

  const max = 720;
  const W = 920, H = 130;
  const padL = 80, padR = 30, padT = 30, padB = 30;
  const innerW = W - padL - padR;
  const tElapsed = startedAt ? Math.min(max, now - startedAt) : 0;
  const headX = padL + (tElapsed / max) * innerW;

  return (
    <Panel title="Failure Cascade Timeline (0-720 s, arXiv:2604.05599 §VI)">
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
          return (
            <g key={i} transform={`translate(${x}, ${padT})`}>
              <line x1={0} y1={4} x2={0} y2={H - padT - padB}
                    stroke={c} strokeDasharray={ev.fired ? "0" : "2 3"} />
              <circle cx={0} cy={H - padT - padB} r={4} fill={c} />
              <text x={4} y={2} fill={c} fontSize={9}>{ev.t_offset_s}s</text>
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
              t = {tElapsed.toFixed(1)}s
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
