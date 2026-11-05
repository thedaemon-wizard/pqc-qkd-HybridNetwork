import type { Ref } from "react";
import { colors } from "../lib/commonStyles";
import { PROTOCOL_NAMES, stateLabel, type Round, type RoundProtocol } from "../lib/sim/qkdRounds";

export const ROUND_VIEW = { W: 640, H: 190, LEFT: 90, RIGHT: 550, Y: 96 } as const;

const NODE_W = 92;
const NODE_H = 44;

/**
 * One round of a protocol, drawn for /qkd-protocols. The photons are moved by the
 * page's animation frame, outside React, and hidden until then. An export is this
 * element serialised, so it says inside itself that it is an idealised round.
 */
export default function QkdRoundSvg({ protocol, round, partIndex, photonRefs, compact }: {
  protocol: RoundProtocol;
  round: Round | null;
  /** The part of the round being shown, or null when it has played. */
  partIndex: number | null;
  photonRefs: Ref<SVGCircleElement>[];
  compact: boolean;
}) {
  const { W, H, LEFT, RIGHT, Y } = ROUND_VIEW;
  const MID = (LEFT + RIGHT) / 2;
  const font = compact ? 18 : 12;
  const smallFont = compact ? 15 : 10.5;
  const shown = (i: number) => round !== null && (partIndex === null || partIndex >= i);
  const measured = protocol === "mdi" ? 2 : 2;
  const box = (x: number, label: string, sub: string, tone: string) => (
    <g>
      <rect x={x - NODE_W / 2} y={Y - NODE_H / 2} width={NODE_W} height={NODE_H} rx={6} fill={colors.panelBg} stroke={tone} strokeWidth={1.5} />
      <text x={x} y={Y - 4} textAnchor="middle" fontSize={font} fill={colors.textPri}>{label}</text>
      <text x={x} y={Y + 13} textAnchor="middle" fontSize={smallFont} fill={colors.textSec}>{sub}</text>
    </g>
  );
  const middle = protocol === "mdi" ? "Relay" : protocol === "bbm92" ? "Source" : null;
  const aliceState = round && shown(0) && (protocol !== "bbm92" || shown(measured))
    ? `${round.alice.basis} basis, ${round.alice.bit} = ${stateLabel(round.alice.basis, round.alice.bit)}` : "";
  const bobState = round && (protocol === "mdi" ? shown(0) : shown(measured))
    ? `${round.bob.basis} basis, ${round.bob.bit} = ${stateLabel(round.bob.basis, round.bob.bit)}` : "";
  const relayText = round?.relay && shown(2)
    ? round.relay === "none" ? "no result" : round.relay === "psi-" ? "ψ−" : "ψ+" : "";
  const verdict = round && partIndex === null
    ? round.kept ? `Kept: shared bit ${round.key}. ${round.why}.` : `Discarded: ${round.why}.`
    : "";
  return (
    <svg id="qkd-round-svg" viewBox={`0 0 ${W} ${H}`} role="img"
         aria-label={`${PROTOCOL_NAMES[protocol]}, one idealised round. ${verdict}`}
         style={{ width: "100%", height: "auto", display: "block", background: colors.panelDark, borderRadius: 8 }}>
      <text x={W / 2} y={compact ? 20 : 16} textAnchor="middle" fontSize={smallFont} fontWeight={600} fill={colors.warn}>
        Idealised round: no loss, no noise, no eavesdropper. Not a rate or a security test.
      </text>
      <line x1={LEFT + NODE_W / 2} y1={Y} x2={(middle ? MID - NODE_W / 2 : RIGHT - NODE_W / 2)} y2={Y} stroke={colors.borderLt} strokeWidth={2} />
      {middle && <line x1={MID + NODE_W / 2} y1={Y} x2={RIGHT - NODE_W / 2} y2={Y} stroke={colors.borderLt} strokeWidth={2} />}
      {box(LEFT, "Alice", protocol === "bbm92" ? "measures" : "prepares", colors.accent)}
      {middle && box(MID, middle, protocol === "mdi" ? "untrusted" : "emits pairs", protocol === "mdi" ? colors.warn : colors.accent)}
      {box(RIGHT, "Bob", protocol === "mdi" ? "prepares" : "measures", colors.accent)}
      {[0, 1].map((i) => (
        <circle key={i} ref={photonRefs[i]} cy={Y} r={compact ? 10 : 6} visibility="hidden" fill={colors.qkd} stroke={colors.textPri} strokeWidth={1} />
      ))}
      <text x={LEFT} y={Y + NODE_H / 2 + (compact ? 22 : 16)} textAnchor="middle" fontSize={smallFont} fill={colors.textSec}>{aliceState}</text>
      <text x={RIGHT} y={Y + NODE_H / 2 + (compact ? 22 : 16)} textAnchor="middle" fontSize={smallFont} fill={colors.textSec}>{bobState}</text>
      {middle && (
        <text x={MID} y={Y - NODE_H / 2 - 6} textAnchor="middle" fontSize={font} fontWeight={600}
              fill={round?.relay === "none" ? colors.danger : colors.success}>{relayText}</text>
      )}
      <text x={W / 2} y={H - (compact ? 10 : 12)} textAnchor="middle" fontSize={compact ? 15 : 12} fontWeight={600}
            fill={round?.kept ? colors.success : colors.textSec}>{verdict}</text>
    </svg>
  );
}
