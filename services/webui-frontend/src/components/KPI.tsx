import { colors, radius, spacing } from "../lib/commonStyles";
import { useNarrowLayout } from "../lib/layout";

export interface KPIProps {
  label: string;
  value: string | number;
}

export default function KPI({ label, value }: KPIProps) {
  const narrow = useNarrowLayout();
  return (
    <div style={{
      background: colors.panelBg, border: `1px solid ${colors.border}`,
      borderRadius: radius.lg, padding: spacing.md,
      // Below 768px (lib/layout.ts) a card may be narrower than its label's
      // longest word, so a row of cards shares the phone's width evenly
      // instead of widening the page; at 375px /paper-flow's row of five
      // cards ran past the right edge. The value gets no overflow-wrap: a
      // number broken over two lines reads as two numbers. A page gives each
      // card room for its value by choosing how many cards share a row. From
      // 768px up the cards size as they always have.
      minWidth: narrow ? 0 : undefined,
    }}>
      {/* break-word, not anywhere: it breaks a word only when the word alone
          would overflow the card, and it does not lower the label's
          min-content width, so a card that fits is laid out as before. */}
      <div style={{ fontSize: 11, color: colors.textMute, marginBottom: 4,
                    overflowWrap: "break-word" }}>
        {label}
      </div>
      <div style={{
        fontSize: 22, color: colors.textPri, fontWeight: 700,
        fontFamily: "monospace",
      }}>{value}</div>
    </div>
  );
}
