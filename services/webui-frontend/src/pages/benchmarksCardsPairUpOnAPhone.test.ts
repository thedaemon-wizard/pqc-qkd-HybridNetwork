/**
 * /benchmarks on a phone: four counter cards, and two charts that must follow
 * the column when the viewport crosses the shell's breakpoint and keep their
 * titles clear of the modebar.
 *
 * Cards. The row was `repeat(4, 1fr)`. At a 320px viewport that leaves each
 * card 37px for its value, and a value such as "0.020" in the cards' 22px
 * monospace measured 55px wide. KPI.tsx leaves the number of cards per row to
 * the page, so below the breakpoint this page puts two per row, each track
 * NARROW_COLUMN, which leaves 112px. From 768px up it is the same four-across
 * row as before (measured: four 240px cards at 1280px, as in the baseline).
 *
 * Charts. Plotly reads its width once, on its first draw, and the shell keeps
 * the page mounted across the breakpoint. Measured on 2026-09-26 without a
 * resize handler: drawn at 1280px and resized to 375px, each chart stayed
 * 996px wide in a 343px column and the page scrolled sideways. With
 * `useResizeHandler` they follow the column, 343px and back to 996px.
 *
 * Titles. The modebar and the centred title share the band at the top of each
 * chart. Measured on 2026-09-26: the modebar is 192px wide and 2-25px from the
 * chart's top, the title 2-18px; at 320px (a 288px chart) the modebar started
 * 94px in, over "BB84 round latency (ms)" at 67-221px, and at 375px 149px in,
 * over the same title at 94-249px. The title is 154px, so left-aligning it
 * would still collide at both widths (154 + 192 = 346px). Below the breakpoint
 * the title now sits on the plot area in a taller top margin: measured at 320,
 * 375, 414 and 600px it runs 33-49px, clear of the modebar, and the plot area
 * stays 200px tall. From 768px up the layout object is what it was, and PLOT_CONFIG,
 * which plotConfigIsPinned.test.ts pins, is not touched.
 *
 * The page is rendered with useNarrowLayout mocked (a server render has no
 * viewport) and with the chart and ExportToolbar stubbed: Plotly needs a
 * browser, and the stub records the props the page gives it.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";

import { readFileSync } from "node:fs";
import { join } from "node:path";

import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";

const viewport = vi.hoisted(() => ({ narrow: false }));
const plotProps = vi.hoisted(() => [] as Record<string, any>[]);
vi.mock("../lib/layout", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../lib/layout")>()),
  useNarrowLayout: () => viewport.narrow,
}));
vi.mock("react-plotly.js", () => ({
  default: (props: Record<string, any>) => { plotProps.push(props); return null; },
}));
vi.mock("../components/ExportToolbar", () => ({ default: () => null }));

import { NARROW_COLUMN } from "../lib/layout";
import { PLOT_CONFIG } from "../lib/plotConfig";
import Benchmarks from "./Benchmarks";

const HERE = new URL(".", import.meta.url).pathname;
const CODE = readFileSync(join(HERE, "Benchmarks.tsx"), "utf8")
  .replace(/\/\*[\s\S]*?\*\//g, "").replace(/(?<!:)\/\/[^\n]*/g, "");

/** Where the modebar's band ends, in px below the chart's top (measured 2026-09-26). */
const MODEBAR_BOTTOM_PX = 25;
/** The height of a chart title's 14px text box (measured 2026-09-26). */
const TITLE_BOX_PX = 16;
/** The two chart titles, in page order. */
const TITLES = ["BB84 round latency (ms)", "QBER history"];

/** The layout prop of each chart, in page order. */
function layouts(narrow: boolean): Record<string, any>[] {
  viewport.narrow = narrow;
  plotProps.length = 0;
  renderToStaticMarkup(createElement(Benchmarks));
  return plotProps.map((p) => p.layout);
}

/** Height of the plot area: the chart less its top and bottom margins. */
const plotArea = (l: Record<string, any>) => l.height - l.margin.t - l.margin.b;

beforeEach(() => { viewport.narrow = false; });

describe("/benchmarks on a phone", () => {
  it("asks lib/layout.ts whether the layout is narrow", () => {
    expect(CODE).toMatch(/import \{[^}]*\bNARROW_COLUMN\b[^}]*\buseNarrowLayout\b[^}]*\} from "\.\.\/lib\/layout"/);
    expect(CODE).toMatch(/const narrow = useNarrowLayout\(\);/);
  });

  it("the cards are two per row when narrow and four across otherwise", () => {
    expect(CODE).toMatch(/const KPI_WIDE_COLUMNS = "repeat\(4, 1fr\)";/);
    expect(CODE).toMatch(/const KPI_NARROW_COLUMNS = `repeat\(2, \$\{NARROW_COLUMN\}\)`;/);
    expect(`repeat(2, ${NARROW_COLUMN})`).toBe("repeat(2, minmax(0, 1fr))");
    expect(CODE).toMatch(/gridTemplateColumns: narrow \? KPI_NARROW_COLUMNS : KPI_WIDE_COLUMNS/);
  });

  it("every chart follows the column when the viewport is resized", () => {
    const plots = [...CODE.matchAll(/<Plot\b([\s\S]*?)\/>/g)].map((m) => m[1]);
    expect(plots.length).toBeGreaterThanOrEqual(2);
    for (const attrs of plots) {
      expect(attrs).toMatch(/\buseResizeHandler\b/);
      expect(attrs).toMatch(/style=\{\{ width: "100%" \}\}/);
    }
  });
});

describe("the chart titles and the modebar", () => {
  it("from 768px up, each chart's layout is the one it had before", () => {
    const wide = layouts(false);
    expect(wide).toHaveLength(2);
    wide.forEach((l, i) => {
      expect(l.height).toBe(260);
      expect(l.margin).toEqual({ l: 50, r: 10, t: 30, b: 30 });
      expect(l.title).toEqual({ text: TITLES[i], font: { color: "#9aa9d8", size: 14 } });
    });
  });

  it("below 768px, each title sits on its plot area rather than in the modebar's band", () => {
    for (const l of layouts(true)) {
      expect(l.title).toMatchObject({ yref: "paper", y: 1, yanchor: "bottom" });
      // Only the placement changes: the text and the font are the same.
      expect(TITLES).toContain(l.title.text);
      expect(l.title.font).toEqual({ color: "#9aa9d8", size: 14 });
      // The title's box, stacked on its pad at the top of the plot area,
      // starts below the modebar's band.
      expect(l.margin.t - l.title.pad.b - TITLE_BOX_PX).toBeGreaterThanOrEqual(MODEBAR_BOTTOM_PX);
    }
  });

  it("below 768px, the chart grows by the added margin, so the plot area keeps its height", () => {
    const wide = layouts(false);
    const narrow = layouts(true);
    narrow.forEach((l, i) => {
      expect(plotArea(l)).toBe(plotArea(wide[i]));
      expect({ ...l.margin, t: 0 }).toEqual({ ...wide[i].margin, t: 0 });
    });
  });

  it("neither branch touches the pinned config", () => {
    for (const narrow of [false, true]) {
      layouts(narrow);
      for (const p of plotProps) expect(p.config).toBe(PLOT_CONFIG);
    }
  });

  it("the QBER chart keeps its fixed y range on both sides of the breakpoint", () => {
    for (const narrow of [false, true]) {
      expect(layouts(narrow)[1].yaxis).toEqual({ range: [0, 0.5], color: "#9aa9d8" });
    }
  });
});
