/**
 * The /keyflow Sankey cannot be read narrower than about 766px.
 *
 * Plotly spaces the six node columns evenly and prints each label beside its
 * node at a fixed 13px, so a narrower chart runs the labels into the next
 * column instead of shrinking them. Measured on 2026-09-26 by drawing the
 * chart at a series of widths and testing every label's box against every
 * other label and node: at 756px "Reconciled (QBER ok)" runs into the
 * "QKD key" node, and from 766px up nothing touches. At a 375px viewport the
 * chart was 343px wide and five labels overlapped, although the page itself
 * did not scroll.
 *
 * So below the shell's breakpoint the chart keeps a named minimum width (800px,
 * measured clean at 375px and 320px) and scrolls sideways inside a
 * ScrollRegion, which never widens the page. The box is outside
 * #keyflow-sankey, so the PNG export still captures the whole chart, and
 * while the chart is wider than it (on a phone) the box is a labelled region
 * the keyboard can reach.
 *
 * A phone's scrollbars are overlays, so nothing on screen said the chart
 * went on: measured on 2026-09-26 at a 375px viewport, the region shows 343px
 * of the 800px chart and the modebar sits at 678-798px of it, out of view
 * until the reader scrolls. A visible line under the chart now says so, when
 * narrow only, in colors.textSec: the muted #6b7796 it had first is about
 * 4.3:1 on the page background, under the 4.5:1 that 12px text needs. The
 * region names that line as its description rather than repeating it in its
 * label, so a screen reader hears it once. From 768px up there is no minimum,
 * no line and no description.
 *
 * The chart's div clips what Plotly draws past its right edge (overflow-x:
 * clip), at every width, so the box sees the chart's width in the div's size.
 * Without it, measured on 2026-09-26, the box stayed a region at 768px after
 * a resize from 375px, and a hover label at the chart's right edge made the
 * box scroll while it showed. With it, the page at 768px and 1280px is pixel
 * for pixel the #133 head's, which had neither the box nor the clip.
 *
 * The page is rendered with useNarrowLayout mocked (a server render has no
 * viewport) and with the chart and ExportToolbar stubbed: Plotly needs a
 * browser, and the stub records the props the page gives it. A server render
 * runs no effects, so the box renders as ScrollRegion's plain div on both
 * sides of the breakpoint: whether it is a region is decided in the browser,
 * from its measured widths
 * (components/scrollRegionIsReachableWhileItScrolls.test.ts).
 */
import { beforeEach, describe, expect, it, vi } from "vitest";

import { readFileSync } from "node:fs";
import { join } from "node:path";

import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";

const viewport = vi.hoisted(() => ({ narrow: false }));
const plotProps = vi.hoisted(() => [] as Record<string, unknown>[]);
vi.mock("../lib/layout", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../lib/layout")>()),
  useNarrowLayout: () => viewport.narrow,
}));
vi.mock("react-plotly.js", async () => {
  const { createElement: h } = await import("react");
  return {
    default: (props: Record<string, unknown>) => {
      plotProps.push(props);
      return h("div", { "data-plot": "" });
    },
  };
});
vi.mock("../components/ExportToolbar", () => ({ default: () => null }));

import { PLOT_CONFIG } from "../lib/plotConfig";
import KeyFlow from "./KeyFlow";

const HERE = new URL(".", import.meta.url).pathname;
const CODE = readFileSync(join(HERE, "KeyFlow.tsx"), "utf8")
  .replace(/\/\*[\s\S]*?\*\//g, "").replace(/(?<!:)\/\/[^\n]*/g, "");

/** The region's name: what it holds, and nothing about how to use it. */
const REGION_LABEL = "Key derivation flow chart";
/** The visible line under the chart on a phone. */
const HINT = "Scroll sideways to see the whole flow.";
/** That line's id, which the region names as its description. */
const HINT_ID = "keyflow-scroll-hint";
/** The markup React gives ScrollRegion's SCROLL_REGION_STYLE. */
const BOX_STYLE = "overflow-x:auto;max-width:100%";
/** The contrast WCAG 2 AA asks of text under 18px (the hint is 12px). */
const AA_SMALL_TEXT_CONTRAST = 4.5;

/** The page's background colour, from index.html's body rule. */
const PAGE_BACKGROUND = /body \{[^}]*background: (#[0-9a-f]{6});/.exec(
  readFileSync(join(HERE, "../../index.html"), "utf8"))?.[1];

/** WCAG 2 relative luminance of a #rrggbb colour. */
function luminance(hex: string): number {
  const [r, g, b] = [1, 3, 5].map((i) => {
    const c = parseInt(hex.slice(i, i + 2), 16) / 255;
    return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

/** WCAG 2 contrast ratio of two #rrggbb colours. */
function contrast(a: string, b: string): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}

function render(narrow: boolean): string {
  viewport.narrow = narrow;
  plotProps.length = 0;
  return renderToStaticMarkup(createElement(MemoryRouter, null, createElement(KeyFlow)));
}

beforeEach(() => { viewport.narrow = false; });

describe("/keyflow on a phone", () => {
  it("asks lib/layout.ts whether the layout is narrow", () => {
    expect(CODE).toMatch(/import \{ useNarrowLayout \} from "\.\.\/lib\/layout";/);
    expect(CODE).toMatch(/const narrow = useNarrowLayout\(\);/);
  });

  it("the minimum chart width is named and clears the measured 766px", () => {
    const m = /const KEY_FLOW_MIN_CHART_PX = (\d+);/.exec(CODE);
    expect(m, "KEY_FLOW_MIN_CHART_PX is not a named constant").not.toBeNull();
    expect(Number(m![1])).toBeGreaterThanOrEqual(766);
  });

  it("the chart scrolls in a ScrollRegion that sits outside the export target", () => {
    expect(CODE).toMatch(/import ScrollRegion(, \{[^}]*\})? from "\.\.\/components\/ScrollRegion";/);
    expect(CODE).toMatch(new RegExp(
      `<ScrollRegion aria-label="${REGION_LABEL}"\\s*`
      + `aria-describedby=\\{narrow \\? NARROW_SCROLL_HINT_ID : undefined\\}>\\s*`
      + `<div id="keyflow-sankey" style=\\{narrow \\? \\{ \\.\\.\\.CHART_CLIP, minWidth: KEY_FLOW_MIN_CHART_PX \\} : CHART_CLIP\\}>`));
    // The page's own box and its hand-made region attributes are gone;
    // ScrollRegion owns them.
    expect(CODE).not.toMatch(/NARROW_CHART_SCROLL/);
    expect(CODE).not.toMatch(/role=\{/);
    expect(CODE).not.toMatch(/tabIndex=\{/);
  });

  it("the region's label names the chart and leaves the instruction to the visible line", () => {
    // Said in both, a screen reader announced "scrolls sideways" twice.
    expect(REGION_LABEL).not.toMatch(/scroll/i);
    expect(CODE).toContain(`const NARROW_SCROLL_HINT_ID = "${HINT_ID}";`);
    expect(CODE).toContain(`const NARROW_SCROLL_HINT = "${HINT}";`);
  });

  it("the chart's div clips what Plotly draws past it, at every width, and makes no scroll box of its own", () => {
    // So the div is as wide as the chart, which is the size ScrollRegion
    // watches: a redraw or a hover label inside it cannot leave the box a
    // region when the chart fits, or make it one for as long as a label shows.
    expect(CODE).toContain('const CHART_CLIP: CSSProperties = { overflowX: "clip" };');
    for (const narrow of [false, true]) {
      expect(render(narrow)).toMatch(/<div id="keyflow-sankey" style="overflow-x:clip[;"]/);
    }
  });

  it("from 768px up: no minimum width, no description, no line under the chart", () => {
    const html = render(false);
    expect(html).toContain(
      `<div style="${BOX_STYLE}"><div id="keyflow-sankey" style="overflow-x:clip"><div data-plot=""></div></div></div>`);
    expect(html).not.toMatch(/role="region"/);
    expect(html).not.toContain(REGION_LABEL);
    expect(html).not.toContain(HINT);
    expect(html).not.toContain(HINT_ID);
  });

  it("below 768px: an 800px chart in the scroll box, and the line right under it", () => {
    // The server render is the plain box; in the browser the 800px chart is
    // wider than any narrow box, so ScrollRegion makes it the region.
    const html = render(true);
    expect(html).toContain(
      `<div style="${BOX_STYLE}">`
      + `<div id="keyflow-sankey" style="overflow-x:clip;min-width:800px"><div data-plot=""></div></div></div>`
      + `<p id="${HINT_ID}" style="color:#9aa9d8;font-size:12px;margin:4px 0 0">${HINT}</p>`);
    // Once, and outside the scrolling box, so it stays in view.
    expect(html.split(HINT)).toHaveLength(2);
  });

  it("the line under the chart reaches AA contrast on the page background", () => {
    const color = /<p id="keyflow-scroll-hint" style="color:(#[0-9a-f]{6});/.exec(render(true))?.[1];
    expect(color, "the hint's colour").toBeDefined();
    expect(PAGE_BACKGROUND, "index.html's body background").toBeDefined();
    expect(contrast(color!, PAGE_BACKGROUND!)).toBeGreaterThanOrEqual(AA_SMALL_TEXT_CONTRAST);
    // The muted colour the line had first did not.
    expect(contrast("#6b7796", PAGE_BACKGROUND!)).toBeLessThan(AA_SMALL_TEXT_CONTRAST);
  });

  it("the chart follows its container when the viewport is resized, with the pinned config", () => {
    for (const narrow of [false, true]) {
      render(narrow);
      expect(plotProps).toHaveLength(1);
      expect(plotProps[0].useResizeHandler).toBe(true);
      expect(plotProps[0].config).toBe(PLOT_CONFIG);
    }
  });
});

describe("the kdf.go snippet is a named Tab stop while it scrolls", () => {
  // Its 448px longest line scrolls in a 286-380px box on a 320-414px phone
  // (2026-09-26). The <pre> scrolls itself, so it takes ScrollRegion's rule
  // directly: the observer hook on the <pre>, and the same attributes.
  const src = readFileSync(join(HERE, "KeyFlow.tsx"), "utf8");
  it("watches the <pre> itself and spreads the region attributes on it", () => {
    expect(src).toMatch(/const \[snippetRef, snippetScrolls\] = useScrollsSideways<HTMLPreElement>\(\);/);
    expect(src).toMatch(/<pre ref=\{snippetRef\} \{\.\.\.scrollRegionAttributes\(snippetScrolls, KDF_SNIPPET_LABEL\)\}/);
    expect(src).toMatch(/const KDF_SNIPPET_LABEL = "[^"]+";/);
  });
});
