/**
 * Pure layout helpers for /protocol-lab's topology drawing, kept out of the
 * component so they can be tested without a DOM.
 */
import type { PresetLink, PresetNode, TopologyPreset } from "./publishedNetworks";
import type { Accounting, LinkState } from "../protocolLabSim";

/** Monospace-ish estimate: the label font is 12 px, about 7.2 px per glyph. */
export const LABEL_FONT_PX = 12;
/**
 * The node labels' font on a phone, in viewBox units. A 640-unit canvas in a
 * 263-318 px panel is scaled by about 0.4-0.5, so 12 units rendered at 5-6 CSS
 * px. 20 units render at 7.5-10 CSS px, and every preset's boxes still fit and
 * stay apart (protocolLabView.test.ts). Link lengths and losses, which cannot
 * fit at that size, are in the "Links as published" table under the drawing.
 */
export const COMPACT_LABEL_FONT_PX = 20;
const GLYPH_EM = 0.6;
const PAD_X = 10;

export interface Box { x: number; y: number; w: number; h: number }

export function nodeBox(n: PresetNode, fontPx: number = LABEL_FONT_PX): Box {
  const w = Math.ceil(n.label.length * GLYPH_EM * fontPx + 2 * PAD_X);
  const h = fontPx + 14;
  return { x: n.x - w / 2, y: n.y - h / 2, w, h };
}

/** True when every node box lies inside the preset's viewBox. */
export function boxesFit(p: TopologyPreset, fontPx: number = LABEL_FONT_PX): boolean {
  const [W, H] = p.viewBox;
  return p.nodes.every((n) => {
    const b = nodeBox(n, fontPx);
    return b.x >= 0 && b.y >= 0 && b.x + b.w <= W && b.y + b.h <= H;
  });
}

/** Short edge label: length (with a dagger when the source gives others) and loss. */
export function edgeLabel(l: PresetLink): string {
  // "not live QKD", not "not QKD": the source says the keys were previously
  // generated and stored, not that they were not QKD output.
  if (l.kind === "non-qkd-keystore") return "keystore (not live QKD)";
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

/** The links' captions, smaller than the nodes' so a node reads first. */
export const EDGE_FONT_PX = 10.5;
/**
 * Width of one caption glyph, in em, for sizing a plate. It covers the longer
 * captions, which come to 0.47-0.53 em per glyph in the page's font; the room
 * kept for DOWN_MARK and the padding cover the shortest ("22 km" is 0.64 em per
 * glyph, its digits being wider than its average). Measured with getBBox on
 * 2026-11-05 at 1280 CSS px: every preset's caption text lies inside its plate.
 */
const EDGE_GLYPH_EM = 0.56;
const EDGE_PAD_X = 4;
const EDGE_PAD_Y = 2;
/** Room for the store gauge under a caption, when the mode has stores. */
export const EDGE_GAUGE_H = 3;
/** Clear space kept around a caption, in viewBox units. */
const EDGE_MARGIN = 2;
/** The mark a downed link's caption gains. Reserved in every caption's width. */
export const DOWN_MARK = "\u2715 ";

/** Where a link's caption goes: a plate centred on (cx, cy), a point on or beside the link. */
export interface EdgeLabelPlace extends Box {
  cx: number;
  cy: number;
  linkId: string;
  text: string;
}

const overlap = (a: Box, b: Box, m = 0) =>
  a.x < b.x + b.w + m && b.x < a.x + a.w + m && a.y < b.y + b.h + m && b.y < a.y + a.h + m;

/** Whether the segment (x1,y1)-(x2,y2) touches `b` (Liang-Barsky clip). */
export function segmentHitsBox(x1: number, y1: number, x2: number, y2: number, b: Box): boolean {
  const dx = x2 - x1, dy = y2 - y1;
  let t0 = 0, t1 = 1;
  for (const [p, q] of [[-dx, x1 - b.x], [dx, b.x + b.w - x1], [-dy, y1 - b.y], [dy, b.y + b.h - y1]]) {
    if (p === 0) { if (q < 0) return false; continue; }
    const r = q / p;
    if (p < 0) { if (r > t1) return false; if (r > t0) t0 = r; }
    else { if (r < t0) return false; if (r < t1) t1 = r; }
  }
  return t0 <= t1;
}

/** Along the link: the middle first, then outwards towards each end. */
const ALONG = [0.5, 0.42, 0.58, 0.34, 0.66, 0.28, 0.72, 0.22, 0.78];
/**
 * Beside the link, in multiples of half the plate's height: on the line first,
 * because a caption on its own line cannot be read as another link's. The last
 * pair clears the node boxes for a caption wider than the gap between them:
 * Tokyo's "keystore (not live QKD)" against a 75-unit gap between K3 and K2.
 */
const BESIDE = [0, 1.15, -1.15, 2.1, -2.1, 3.4, -3.4];
/** Costs. A caption over a foreign line is worse than any move along its own. */
const COST_ALONG = 10;
const COST_BESIDE = 4;
const COST_FOREIGN_LINE = 100;

/**
 * Place every link's caption so that no two captions touch, no caption touches
 * a node, and, where any place allows it, no caption lies over another link.
 *
 * The plate under a caption hides its own line, which is what stops the line
 * striking through the text. Pure and deterministic: the same preset always
 * draws the same way, so an exported PNG is reproducible. Shortest links go
 * first, because they have the fewest places to offer.
 */
export function placeEdgeLabels(p: TopologyPreset): Map<string, EdgeLabelPlace> {
  const [W, H] = p.viewBox;
  const nodes = new Map(p.nodes.map((n) => [n.id, n]));
  const boxes = p.nodes.map((n) => nodeBox(n));
  const lengthOf = (l: PresetLink) => {
    const a = nodes.get(l.a)!, b = nodes.get(l.b)!;
    return Math.hypot(b.x - a.x, b.y - a.y);
  };
  const order = [...p.links].sort((x, y) => lengthOf(x) - lengthOf(y) || x.id.localeCompare(y.id));
  const placed = new Map<string, EdgeLabelPlace>();
  for (const l of order) {
    const a = nodes.get(l.a)!, b = nodes.get(l.b)!;
    const text = edgeLabel(l);
    const w = Math.ceil((text.length + DOWN_MARK.length) * EDGE_GLYPH_EM * EDGE_FONT_PX + 2 * EDGE_PAD_X);
    const h = Math.ceil(EDGE_FONT_PX + 2 * EDGE_PAD_Y + EDGE_GAUGE_H);
    const len = lengthOf(l) || 1;
    const [nx, ny] = [-(b.y - a.y) / len, (b.x - a.x) / len];
    let best: EdgeLabelPlace | null = null;
    let bestCost = Infinity;
    for (const t of ALONG) {
      for (const side of BESIDE) {
        const off = side * (h / 2);
        const cx = a.x + (b.x - a.x) * t + nx * off;
        const cy = a.y + (b.y - a.y) * t + ny * off;
        const box: Box = { x: cx - w / 2, y: cy - h / 2, w, h };
        if (box.x < 0 || box.y < 0 || box.x + w > W || box.y + h > H) continue;
        if (boxes.some((n) => overlap(box, n, EDGE_MARGIN))) continue;
        if ([...placed.values()].some((o) => overlap(box, o, EDGE_MARGIN))) continue;
        const foreign = p.links.filter((o) => o.id !== l.id).filter((o) => {
          const oa = nodes.get(o.a)!, ob = nodes.get(o.b)!;
          return segmentHitsBox(oa.x, oa.y, ob.x, ob.y, box);
        }).length;
        const cost = COST_ALONG * Math.abs(t - 0.5) * 10 + COST_BESIDE * Math.abs(side) + COST_FOREIGN_LINE * foreign;
        if (cost < bestCost) {
          bestCost = cost;
          best = { ...box, cx, cy, linkId: l.id, text };
        }
      }
    }
    if (best === null) throw new Error(`no place for the caption of ${l.id} in ${p.meta.id}`);
    placed.set(l.id, best);
  }
  return placed;
}

/** The links along a list of nodes, in order; a pair with no link is left out. */
export function linksAlong(p: TopologyPreset, nodes: readonly string[]): string[] {
  const ids: string[] = [];
  for (let i = 0; i + 1 < nodes.length; i++) {
    const l = p.links.find((x) => (x.a === nodes[i] && x.b === nodes[i + 1]) || (x.b === nodes[i] && x.a === nodes[i + 1]));
    if (l) ids.push(l.id);
  }
  return ids;
}

/**
 * How full a link's store is, for the gauge under its caption, or null where
 * the mode tracks no store on the link. Keys are shown against the level where
 * production pauses, which is as full as a store gets (KeyPool's low watermark);
 * cited stores share one scale, the largest cited store.
 */
export function storeFill(l: LinkState, accounting: Accounting, scaleBits: number | null): number | null {
  if (accounting === "keys" && l.storedKeys !== null && l.fillToKeys) {
    return Math.max(0, Math.min(1, l.storedKeys / l.fillToKeys));
  }
  if (accounting === "stores" && l.storedBits !== null && scaleBits) {
    return Math.max(0, Math.min(1, l.storedBits / scaleBits));
  }
  return null;
}
