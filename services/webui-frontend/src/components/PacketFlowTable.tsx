/**
 * Packet Flow Inspector (Phase 14).
 *
 * Tabular per-phase view: phase, name, packets, bytes, period, grace, status.
 */
import Panel from "./Panel";
import { colors } from "../lib/commonStyles";
import type { PhaseBudget } from "./PhaseSequenceSvg";

export interface PacketFlowTableProps {
  budgets: PhaseBudget[];
  currentPhase: number;
}

export default function PacketFlowTable({ budgets, currentPhase }: PacketFlowTableProps) {
  return (
    <Panel title="Packet Flow Inspector (paper budgets, arXiv:2604.05599 §IV-B)">
      <table style={{ width: "100%", fontSize: 12, color: colors.textPri,
                       borderCollapse: "collapse" }}>
        <thead>
          <tr style={{ color: colors.textMute, textAlign: "left" }}>
            <th style={{ padding: "4px 6px" }}>#</th>
            <th>Phase name</th>
            <th style={{ textAlign: "right" }}>Packets</th>
            <th style={{ textAlign: "right" }}>Bytes</th>
            <th style={{ textAlign: "right" }}>Period</th>
            <th style={{ textAlign: "right" }}>Grace</th>
            <th>Status</th>
          </tr>
        </thead>
        <tbody>
          {budgets.map((b) => {
            const active = b.phase === currentPhase;
            return (
              <tr key={b.phase}
                  style={{ borderTop: `1px solid ${colors.border}`,
                            background: active ? "#1a2440" : "transparent" }}>
                <td style={{ padding: "4px 6px" }}>{b.phase}</td>
                <td>{b.name}</td>
                <td style={{ textAlign: "right", fontFamily: "monospace" }}>{b.packets}</td>
                <td style={{ textAlign: "right", fontFamily: "monospace" }}>{b.bytes}</td>
                <td style={{ textAlign: "right", fontFamily: "monospace" }}>
                  {b.period_s ? `${b.period_s}s` : "—"}
                </td>
                <td style={{ textAlign: "right", fontFamily: "monospace" }}>{b.grace_s}s</td>
                <td>{active ? "active" : "idle"}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </Panel>
  );
}
