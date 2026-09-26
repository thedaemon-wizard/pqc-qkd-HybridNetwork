import type { CSSProperties, ReactNode } from "react";
import { colors, radius, spacing } from "../lib/commonStyles";
import { useNarrowLayout } from "../lib/layout";

export interface PanelProps {
  title?: ReactNode;
  children: ReactNode;
  accent?: string;        // optional left-border accent colour
  style?: CSSProperties;
}

export default function Panel({ title, children, accent, style }: PanelProps) {
  const narrow = useNarrowLayout();
  return (
    <div style={{
      background: colors.panelBg,
      border: `1px solid ${colors.border}`,
      borderLeft: accent ? `4px solid ${accent}` : undefined,
      borderRadius: radius.lg,
      padding: spacing.md,
      // Below 768px (lib/layout.ts) a panel may be narrower than its content's
      // intrinsic width, so a grid or flex row of panels fits the phone
      // instead of pushing the page sideways. Content wider than the panel
      // then needs its own overflow-x container: a <pre> with overflow-x:
      // auto scrolls itself, a bare <table> does not. Only below 768px:
      // measured on 2026-09-26, the same rule at 768px re-balanced
      // /paper-flow's two-column grid, whose tracks size to their content
      // (the packet flow inspector went from 305px to 234px wide), so it is
      // not width-neutral there.
      minWidth: narrow ? 0 : undefined,
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
