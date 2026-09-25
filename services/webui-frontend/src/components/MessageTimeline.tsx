import { colors } from "../lib/commonStyles";
import type { TimelineMessage } from "../lib/sim/protocolLabSim";

/**
 * Two lanes: this stack's ETSI GS QKD 014 message shapes per hop (sizes in
 * bits), and the simulated ETSI GS QKD 004 V2.1.1 calls end to end (chunk
 * sizes in bytes, statuses from Table 2). Aggregated per tick.
 */
export default function MessageTimeline({ messages }: { messages: TimelineMessage[] }) {
  const lane = (l: "014" | "004") => messages.filter((m) => m.lane === l).slice(-12);
  const col = (title: string, items: TimelineMessage[]) => (
    <div style={{ flex: "1 1 320px", minWidth: 0 }}>
      <div style={{ fontSize: 12, color: colors.textPri, fontWeight: 600, marginBottom: 4 }}>{title}</div>
      {items.length === 0 ? <div style={{ fontSize: 11, color: colors.textMute }}>no messages yet</div> : (
        <ol style={{ margin: 0, paddingLeft: 18, fontSize: 11, color: colors.textSec, fontFamily: "monospace" }}>
          {items.map((m, i) => (
            <li key={i} style={{ overflowWrap: "anywhere" }}>
              t={m.t_s}s {m.text}
              {m.transition ? ` [${m.transition}]` : ""}
            </li>
          ))}
        </ol>
      )}
    </div>
  );
  return (
    <div style={{ display: "flex", gap: 16, flexWrap: "wrap" }}>
      {col("ETSI GS QKD 014: message shapes of this stack's 014 API, simulated per hop (sizes in bits)", lane("014"))}
      {col("ETSI GS QKD 004 V2.1.1: simulated end to end (Key_chunk_size in bytes, status per Table 2)", lane("004"))}
    </div>
  );
}
