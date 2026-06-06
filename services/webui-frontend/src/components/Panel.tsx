import type { CSSProperties, ReactNode } from "react";
import { colors, radius, spacing } from "../lib/commonStyles";

export interface PanelProps {
  title?: ReactNode;
  children: ReactNode;
  accent?: string;        // optional left-border accent colour
  style?: CSSProperties;
}

export default function Panel({ title, children, accent, style }: PanelProps) {
  return (
    <div style={{
      background: colors.panelBg,
      border: `1px solid ${colors.border}`,
      borderLeft: accent ? `4px solid ${accent}` : undefined,
      borderRadius: radius.lg,
      padding: spacing.md,
      ...style,
    }}>
      {title && (
        <h3 style={{
          margin: 0, marginBottom: spacing.sm,
          fontSize: 14, color: colors.textSec,
        }}>
          {title}
        </h3>
      )}
      {children}
    </div>
  );
}
