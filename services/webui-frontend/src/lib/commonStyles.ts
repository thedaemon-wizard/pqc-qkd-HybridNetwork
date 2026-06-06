/**
 * Shared dark-theme tokens (Phase 12-B).
 *
 * Replaces hard-coded hex literals scattered across all pages.
 */
export const colors = {
  bg:        "#0a0e17",
  panelBg:   "#0d1320",
  panelDark: "#070b14",
  border:    "#1d2741",
  borderLt:  "#2a3760",
  textPri:   "#d8e1ff",
  textSec:   "#9aa9d8",
  textMute:  "#6b7796",
  accent:    "#5b8def",
  success:   "#3ddc84",
  warn:      "#f5a623",
  danger:    "#e25555",
  pqc:       "#e91e63",
  qkd:       "#f0a020",
  vpn:       "#7c5cff",
  active:    "#1a2440",
} as const;

export const spacing = {
  xs: 4,
  sm: 8,
  md: 12,
  lg: 16,
  xl: 24,
} as const;

export const radius = { sm: 4, md: 6, lg: 8 } as const;
