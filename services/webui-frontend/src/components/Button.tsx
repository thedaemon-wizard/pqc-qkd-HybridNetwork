import type { CSSProperties, ReactNode } from "react";
import { colors, radius } from "../lib/commonStyles";

type Variant = "primary" | "secondary" | "danger" | "success" | "warn" | "ghost";
type Size = "sm" | "md";

const variantColor: Record<Variant, string> = {
  primary:   colors.accent,
  secondary: colors.borderLt,
  danger:    colors.danger,
  success:   colors.success,
  warn:      colors.warn,
  ghost:     "transparent",
};

const variantFg: Record<Variant, string> = {
  primary: "#fff", secondary: colors.textPri, danger: "#fff",
  success: "#fff", warn: "#fff", ghost: colors.textSec,
};

export interface ButtonProps {
  children: ReactNode;
  onClick?: () => void;
  variant?: Variant;
  size?: Size;
  disabled?: boolean;
  title?: string;
  style?: CSSProperties;
}

export default function Button({
  children, onClick, variant = "primary", size = "md",
  disabled, title, style,
}: ButtonProps) {
  const bg = variantColor[variant];
  const fg = variantFg[variant];
  const padding = size === "sm" ? "4px 10px" : "6px 14px";
  const fontSize = size === "sm" ? 11 : 13;
  const border = variant === "ghost"
    ? `1px solid ${colors.borderLt}`
    : "none";
  return (
    <button onClick={onClick} disabled={disabled} title={title}
            style={{
              background: bg, color: fg, border, borderRadius: radius.sm,
              padding, fontSize, fontWeight: 600,
              cursor: disabled ? "not-allowed" : "pointer",
              opacity: disabled ? 0.5 : 1,
              ...style,
            }}>
      {children}
    </button>
  );
}
