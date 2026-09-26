/**
 * /topology draws its four nodes on a 760x460 canvas and scales the canvas to
 * the width of the page. The force layout fills only about the middle half of
 * that canvas, so on a phone the drawing came out tiny.
 *
 * Measured on 2026-09-26 at a 375px viewport: the SVG was 345px wide, a scale
 * of 0.45, so the 10px edge labels and node captions rendered at 4.5px. Nothing
 * scrolled sideways; it simply could not be read.
 *
 * Below the shell's breakpoint the viewBox is now the drawing's own bounding
 * box plus a margin, measured in the browser so it follows wherever the forces
 * settle: the same labels render at about 9px at 375px (7.4px at 320px). The
 * SVG is capped at one CSS px per viewBox unit, so a wider phone (600px) shows
 * the drawing at its designed size instead of scaling it up by 1.47. From
 * 768px up the viewBox is the whole canvas, uncapped, as before.
 */
import { describe, expect, it } from "vitest";

import { readFileSync } from "node:fs";
import { join } from "node:path";

import { fittedViewBox } from "./Topology";

const HERE = new URL(".", import.meta.url).pathname;
/** Topology.tsx without its comments. */
const CODE = readFileSync(join(HERE, "Topology.tsx"), "utf8")
  .replace(/\/\*[\s\S]*?\*\//g, "").replace(/(?<!:)\/\/[^\n]*/g, "");

describe("fittedViewBox", () => {
  it("adds the same margin on every side", () => {
    const box = fittedViewBox({ x: 200, y: 100, width: 300, height: 200 });
    const margin = 200 - box.x;
    expect(margin).toBeGreaterThan(0);
    expect(box).toEqual({ x: 200 - margin, y: 100 - margin, width: 300 + 2 * margin, height: 200 + 2 * margin });
  });

  it("rounds outwards, so the drawing is never cut and a sub-pixel move changes nothing", () => {
    const a = fittedViewBox({ x: 200.2, y: 100.7, width: 299.5, height: 199.1 });
    const b = fittedViewBox({ x: 200.4, y: 100.9, width: 299.4, height: 199.0 });
    expect(a).toEqual(b);
    for (const v of [a.x, a.y, a.width, a.height]) expect(Number.isInteger(v)).toBe(true);
    // Contains the unrounded box.
    expect(a.x).toBeLessThanOrEqual(200.2);
    expect(a.x + a.width).toBeGreaterThanOrEqual(200.2 + 299.5);
    expect(a.y + a.height).toBeGreaterThanOrEqual(100.7 + 199.1);
  });
});

describe("/topology on a phone", () => {
  it("asks lib/layout.ts whether the layout is narrow", () => {
    expect(CODE).toMatch(/import \{ useNarrowLayout \} from "\.\.\/lib\/layout";/);
    expect(CODE).toMatch(/const narrow = useNarrowLayout\(\);/);
  });

  it("crops to the measured drawing only when narrow", () => {
    expect(CODE).toMatch(/if \(!narrow \|\| !drawingRef\.current\) return;/);
    expect(CODE).toMatch(/drawingRef\.current\.getBBox\(\)/);
    expect(CODE).toMatch(/const fitted = narrow && fitBox \? fitBox : null;/);
    // Everything drawn is inside the measured group.
    expect(CODE).toMatch(/<svg id="topology-svg"[\s\S]*?>\s*<g ref=\{drawingRef\}>/);
    expect(CODE).toMatch(/\}\)\}\s*<\/g>\s*<\/svg>/);
  });

  it("keeps the whole canvas, uncapped, when not narrow", () => {
    expect(CODE).toMatch(/: `0 0 \$\{WIDTH\} \$\{HEIGHT\}`/);
    expect(CODE).toMatch(/\.\.\.\(fitted \? \{ display: "block", maxWidth: fitted\.width, marginInline: "auto" \} : \{\}\)/);
  });
});
