/**
 * 5-phase swimlane sequence diagram (Phase 14).
 *
 * Horizontal time axis 0..540s; vertical swimlanes per phase, each with a
 * packet-count badge and a bar whose width is proportional to the packet
 * budget (Rosenpass Phase 4 dominates at 4772B).
 */
import { colors } from "../lib/commonStyles";

export interface PhaseBudget {
  phase: number;
  name: string;
  packets: number;
  bytes: number;
  period_s: number | null;
  grace_s: number;
  description: string;
}

export interface PhaseSequenceProps {
  budgets: PhaseBudget[];
  currentPhase: number;
}

export default function PhaseSequenceSvg({ budgets, currentPhase }: PhaseSequenceProps) {
  const W = 1100, H = 360;
  const padL = 230, padR = 30, padT = 36, padB = 40;
  const innerW = W - padL - padR;
  const innerH = H - padT - padB;
  const laneH = innerH / 5;
  const tMax = 540;

  const phaseColor: Record<number, string> = {
    1: colors.vpn, 2: colors.qkd, 3: colors.pqc, 4: colors.danger,
    5: colors.accent,
  };

  // Largest bytes for scaling
  const maxBytes = Math.max(...budgets.map((b) => b.bytes || 0), 1);

  return (
    <svg id="paper-flow-sequence-svg" viewBox={`0 0 ${W} ${H}`}
         style={{ width: "100%" }}
         role="img"
         aria-label="5-phase Data Exchange sequence diagram">
      {/* Time axis */}
      <line x1={padL} y1={H - padB} x2={W - padR} y2={H - padB}
            stroke={colors.borderLt} />
      {[0, 60, 120, 180, 240, 300, 360, 420, 480, 540].map((t) => {
        const x = padL + (t / tMax) * innerW;
        return (
          <g key={t}>
            <line x1={x} y1={H - padB} x2={x} y2={H - padB + 4}
                  stroke={colors.textMute} />
            <text x={x} y={H - padB + 16} fill={colors.textMute}
                  fontSize={9} textAnchor="middle">{t}s</text>
          </g>
        );
      })}
      <text x={padL + innerW / 2} y={H - 4} fill={colors.textSec}
            fontSize={11} textAnchor="middle">Time (seconds)</text>

      {/* Lanes */}
      {budgets.slice(0, 5).map((b, i) => {
        const y = padT + i * laneH;
        const active = b.phase === currentPhase;
        const c = phaseColor[b.phase] ?? colors.accent;
        const bytesW = b.bytes > 0
          ? Math.max(8, (b.bytes / maxBytes) * 200)
          : 6;
        return (
          <g key={b.phase}>
            {/* lane separator */}
            <line x1={padL} y1={y} x2={W - padR} y2={y}
                  stroke={colors.border} strokeDasharray="2 3" />
            {/* phase label + packet badge */}
            <text x={20} y={y + laneH / 2 - 4} fill={c}
                  fontSize={12} fontWeight={700}>
              Phase {b.phase}
            </text>
            <text x={20} y={y + laneH / 2 + 12} fill={colors.textSec}
                  fontSize={10}>{b.name}</text>
            <rect x={140} y={y + laneH / 2 - 12} width={80} height={24} rx={4}
                  fill={`${c}25`} stroke={c} />
            <text x={180} y={y + laneH / 2 + 4} fill={c}
                  fontSize={11} fontWeight={700} textAnchor="middle">
              {b.packets}pkt / {b.bytes}B
            </text>

            {/* Grace window band (semi-transparent) */}
            {b.grace_s > 0 && (
              <rect x={padL}
                    y={y + laneH / 2 - 8}
                    width={(b.grace_s / tMax) * innerW}
                    height={16} rx={2}
                    fill={`${c}15`} stroke={`${c}40`} />
            )}

            {/* Period markers if recurring */}
            {b.period_s && [0, b.period_s, b.period_s * 2, b.period_s * 3, b.period_s * 4]
              .filter((t) => t <= tMax)
              .map((t) => {
                const x = padL + (t / tMax) * innerW;
                return (
                  <circle key={t} cx={x} cy={y + laneH / 2}
                          r={5} fill={c}
                          stroke={active ? "#fff" : c} strokeWidth={1}
                          style={{
                            filter: active
                              ? `drop-shadow(0 0 4px ${c})`
                              : "none",
                          }} />
                );
              })}

            {/* Bytes-proportional bar */}
            <rect x={padL + 4}
                  y={y + laneH - 14}
                  width={bytesW} height={6} rx={2}
                  fill={c} opacity={active ? 1 : 0.5} />
          </g>
        );
      })}
    </svg>
  );
}
