/**
 * /protocol-lab's topology drawing: captions and boxes that can be read.
 *
 * Reported on 2026-11-05 and reproduced on the public page at 1024 and 1280 CSS
 * px: SECOQC's "25 km, 5.75 dB" lay over "22 km" where its two diagonals cross
 * (476 square px of overlap), MadQCI's "24.5 km, 8.72 dB" and "7.8 km †, 1.40
 * dB" were cut by node boxes, and lines ran through the captions of the
 * vertical and diagonal links on Tokyo, SECOQC and MadQCI. Each caption was
 * placed at its link's midpoint and nothing checked it against anything.
 */
import { describe, expect, it } from "vitest";

import { PRESETS } from "./publishedNetworks";
import {
  COMPACT_LABEL_FONT_PX, boxesFit, nodeBox, placeEdgeLabels, segmentHitsBox, type Box,
} from "./view";

const touch = (a: Box, b: Box) =>
  a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;

describe.each(PRESETS.map((p) => [p.meta.id, p] as const))("%s", (_id, preset) => {
  const placed = placeEdgeLabels(preset);
  const places = [...placed.values()];
  const nodes = new Map(preset.nodes.map((n) => [n.id, n]));

  it("gives every link a caption", () => {
    expect([...placed.keys()].sort()).toEqual(preset.links.map((l) => l.id).sort());
  });

  it("keeps every caption inside the canvas", () => {
    const [W, H] = preset.viewBox;
    for (const b of places) {
      expect(b.x, b.linkId).toBeGreaterThanOrEqual(0);
      expect(b.y, b.linkId).toBeGreaterThanOrEqual(0);
      expect(b.x + b.w, b.linkId).toBeLessThanOrEqual(W);
      expect(b.y + b.h, b.linkId).toBeLessThanOrEqual(H);
    }
  });

  it("lets no two captions touch", () => {
    for (const [i, a] of places.entries()) {
      for (const b of places.slice(i + 1)) {
        expect(touch(a, b), `${a.linkId} and ${b.linkId}`).toBe(false);
      }
    }
  });

  it("lets no caption touch a node", () => {
    for (const b of places) {
      for (const n of preset.nodes) {
        expect(touch(b, nodeBox(n)), `${b.linkId} and ${n.id}`).toBe(false);
      }
    }
  });

  it("lays no caption over another link", () => {
    for (const b of places) {
      for (const l of preset.links) {
        if (l.id === b.linkId) continue;
        const u = nodes.get(l.a)!, v = nodes.get(l.b)!;
        expect(segmentHitsBox(u.x, u.y, v.x, v.y, b), `${b.linkId} over ${l.id}`).toBe(false);
      }
    }
  });

  it("keeps each caption nearer its own link than any other", () => {
    const toSegment = (x: number, y: number, u: { x: number; y: number }, v: { x: number; y: number }) => {
      const [dx, dy] = [v.x - u.x, v.y - u.y];
      const t = Math.max(0, Math.min(1, ((x - u.x) * dx + (y - u.y) * dy) / (dx * dx + dy * dy)));
      return Math.hypot(x - (u.x + t * dx), y - (u.y + t * dy));
    };
    for (const l of preset.links) {
      const b = placed.get(l.id)!;
      const own = toSegment(b.cx, b.cy, nodes.get(l.a)!, nodes.get(l.b)!);
      for (const o of preset.links) {
        if (o.id === l.id) continue;
        const other = toSegment(b.cx, b.cy, nodes.get(o.a)!, nodes.get(o.b)!);
        expect(own, `${l.id} is nearer ${o.id}`).toBeLessThan(other);
      }
    }
  });

  it("draws the same way every time, so an exported PNG is reproducible", () => {
    expect([...placeEdgeLabels(preset).entries()]).toEqual([...placed.entries()]);
  });

  it("fits its node boxes at the phone's larger font, and they stay apart", () => {
    expect(boxesFit(preset, COMPACT_LABEL_FONT_PX)).toBe(true);
    const boxes = preset.nodes.map((n) => ({ id: n.id, b: nodeBox(n, COMPACT_LABEL_FONT_PX) }));
    for (const [i, a] of boxes.entries()) {
      for (const c of boxes.slice(i + 1)) {
        expect(touch(a.b, c.b), `${a.id} and ${c.id}`).toBe(false);
      }
    }
  });
});

describe("segmentHitsBox", () => {
  const box = { x: 10, y: 10, w: 10, h: 10 };
  it("sees a segment through the box, into it and beside it", () => {
    expect(segmentHitsBox(0, 15, 30, 15, box)).toBe(true);
    expect(segmentHitsBox(0, 0, 30, 30, box)).toBe(true);
    expect(segmentHitsBox(15, 15, 15, 40, box)).toBe(true);
    expect(segmentHitsBox(0, 5, 30, 5, box)).toBe(false);
    expect(segmentHitsBox(0, 25, 8, 35, box)).toBe(false);
  });
});
