import { colors, radius, spacing } from "../lib/commonStyles";

export interface KPIProps {
  label: string;
  value: string | number;
}

export default function KPI({ label, value }: KPIProps) {
  return (
    <div style={{
      background: colors.panelBg, border: `1px solid ${colors.border}`,
      borderRadius: radius.lg, padding: spacing.md,
    }}>
      <div style={{ fontSize: 11, color: colors.textMute, marginBottom: 4 }}>
        {label}
      </div>
      <div style={{
        fontSize: 22, color: colors.textPri, fontWeight: 700,
        fontFamily: "monospace",
      }}>{value}</div>
    </div>
  );
}
