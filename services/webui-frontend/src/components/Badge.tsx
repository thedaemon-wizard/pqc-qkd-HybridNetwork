import { colors } from "../lib/commonStyles";

const STATUS_COLOR: Record<string, string> = {
  running:     colors.success,
  established: colors.success,
  healthy:     colors.success,
  restarting:  colors.warn,
  rekeying:    colors.warn,
  created:     colors.accent,
  starting:    colors.accent,
  paused:      colors.warn,
  exited:      colors.danger,
  stopped:     colors.danger,
  dead:        colors.danger,
  down:        colors.danger,
  absent:      "#445",
  unknown:     "#445",
  idle:        "#445",
};

export interface BadgeProps {
  text: string;
  color?: string;       // explicit override
}

export default function Badge({ text, color }: BadgeProps) {
  const bg = color ?? STATUS_COLOR[text] ?? "#445";
  return (
    <span style={{
      display: "inline-flex", alignItems: "center",
      padding: "2px 8px", borderRadius: 12,
      background: bg, color: "#fff",
      fontSize: 11, fontWeight: 600,
    }}>{text}</span>
  );
}
