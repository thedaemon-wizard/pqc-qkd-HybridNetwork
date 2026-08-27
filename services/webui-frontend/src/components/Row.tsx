import type { ReactNode } from "react";
import { colors } from "../lib/commonStyles";

export default function Row({ k, v }: { k: string; v: ReactNode }) {
  return (
    // NOTE: nothing imports this component. Three pages carry their own
    // near-identical copies instead (VpnProtocols, PQCValidator,
    // QuantumSecureE2E). Fixed here anyway so it does not reintroduce the
    // defect if it is ever adopted -- see the comment in VpnProtocols.tsx.
    <div style={{
      display: "flex", justifyContent: "space-between", gap: 12,
      padding: "3px 0", fontSize: 12, fontFamily: "monospace",
    }}>
      <span style={{ color: colors.textSec, flexShrink: 0 }}>{k}</span>
      <span style={{ color: colors.textPri, minWidth: 0, textAlign: "right",
                     overflowWrap: "anywhere" }}>{v}</span>
    </div>
  );
}
