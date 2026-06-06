import type { ReactNode } from "react";
import { colors } from "../lib/commonStyles";

export default function Row({ k, v }: { k: string; v: ReactNode }) {
  return (
    <div style={{
      display: "flex", justifyContent: "space-between",
      padding: "3px 0", fontSize: 12, fontFamily: "monospace",
    }}>
      <span style={{ color: colors.textSec }}>{k}</span>
      <span style={{ color: colors.textPri }}>{v}</span>
    </div>
  );
}
