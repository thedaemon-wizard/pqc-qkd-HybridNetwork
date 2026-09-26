/**
 * Packet Flow Inspector (Phase 14).
 *
 * Tabular per-phase view: phase, name, packets, bytes, period, grace, status.
 */
import Panel from "./Panel";
import ScrollRegion from "./ScrollRegion";
import { colors } from "../lib/commonStyles";
import type { PhaseBudget } from "./PhaseSequenceSvg";

export interface PacketFlowTableProps {
  budgets: PhaseBudget[];
  currentPhase: number;
}

export default function PacketFlowTable({ budgets, currentPhase }: PacketFlowTableProps) {
  return (
    <Panel title="Packet Flow Inspector (paper budgets, arXiv:2604.05599 Evaluation Test 1)">
      {/* The table scrolls inside this box when the panel is narrower than
          the table can wrap to. Measured on 2026-09-26 in headless Chrome:
          its seven columns are 280px wide at their narrowest, a 320px phone
          leaves the box 263px, and a table does not shrink below its
          narrowest, so without the box it ran out of the panel. At 375px the
          box is 318px and the table fits. At 768px and 1280px the box is
          exactly as wide as the table (280px and 465px), and the table, both
          panels, the cascade drawing and the KPI cards are the same width
          with and without it. While the table is wider than the box, as at
          320px, the box is also a named region the keyboard can reach
          (ScrollRegion); while it fits, it is a plain div. */}
      <ScrollRegion aria-label="Packet flow table">
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
      </ScrollRegion>
    </Panel>
  );
}
