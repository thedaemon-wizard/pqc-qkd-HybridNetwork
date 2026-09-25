/**
 * Pure layout helpers for /protocol-lab's topology drawing, kept out of the
 * component so they can be tested without a DOM.
 */
import type { PresetLink, PresetNode, TopologyPreset } from "./publishedNetworks";

/** Monospace-ish estimate: the label font is 12 px, about 7.2 px per glyph. */
export const LABEL_FONT_PX = 12;
const GLYPH_PX = 7.2;
const PAD_X = 10;

export function nodeBox(n: PresetNode): { x: number; y: number; w: number; h: number } {
  const w = Math.ceil(n.label.length * GLYPH_PX + 2 * PAD_X);
  const h = LABEL_FONT_PX + 14;
  return { x: n.x - w / 2, y: n.y - h / 2, w, h };
}

/** True when every node box lies inside the preset's viewBox. */
export function boxesFit(p: TopologyPreset): boolean {
  const [W, H] = p.viewBox;
  return p.nodes.every((n) => {
    const b = nodeBox(n);
    return b.x >= 0 && b.y >= 0 && b.x + b.w <= W && b.y + b.h <= H;
  });
}

/** Short edge label: length (with a dagger when the source gives others) and loss. */
export function edgeLabel(l: PresetLink): string {
  if (l.kind === "non-qkd-keystore") return "keystore (not QKD)";
  const len = l.length ? `${l.length.printed} ${l.length.unit}${l.lengthAlt.length ? "†" : ""}` : "";
  const loss = l.loss
    ? `${l.loss.qualifier && ["~", ">", "<"].includes(l.loss.qualifier) ? l.loss.qualifier : ""}${l.loss.printed} dB`
    : "";
  return [len, loss].filter(Boolean).join(", ");
}

export function midpoint(p: TopologyPreset, l: PresetLink): { x: number; y: number } {
  const a = p.nodes.find((n) => n.id === l.a)!;
  const b = p.nodes.find((n) => n.id === l.b)!;
  return { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 };
}
