/**
 * /bb84 fits a phone, and is unchanged from 768px up.
 *
 * Once the shell dropped its 220px sidebar below 768px (lib/layout.ts), the
 * page itself still had two `1fr 1fr` grids sized for a desktop. Measured on
 * 2026-09-26 with the collapsed shell in place:
 *
 *   - The page scrolled sideways by 82px at 375px, 137px at 320px and 43px at
 *     414px. A bare `1fr` track is minmax(auto, 1fr), so the engine stats
 *     <pre> in the second row widened its column to its longest JSON line and
 *     pushed the row past the screen.
 *   - The two charts were half of a 343px column each at 375px, and the QBER
 *     chart's title took four lines above them.
 *   - Resizing across the breakpoint left the charts at the old column's
 *     width: Plotly reads its container once, on the first draw. With
 *     `autosize` on, a chart still at that width held its `1fr` track open
 *     and re-measured the container it was propping: loading at 1280px, going
 *     to 375px and back, the charts settled at 590px in 616px cards and the
 *     page scrolled 220px sideways, until the cards got minWidth: 0.
 *   - At 320px the abort line's label, 283px of text anchored at the right of
 *     a 212px plot area, lost its first words off the chart's left edge.
 *
 * The fix is conditional on the one breakpoint: one column and a two-line
 * label below 768px, the old templates and label, passed through unchanged,
 * above it. The charts follow their container at every width, and the <pre>
 * and table scroll inside their cards if they ever outgrow them. At 768px and
 * 1280px the cards and charts measure as before (234px and 490px cards, 208px
 * and 464px charts); a fresh load is otherwise different only in live data.
 */
import { describe, expect, it } from "vitest";

import { readFileSync } from "node:fs";
import { join } from "node:path";

import { NARROW_LAYOUT_MAX_PX } from "../lib/layout";

const HERE = new URL(".", import.meta.url).pathname;
const PAGE = readFileSync(join(HERE, "BB84.tsx"), "utf8");

/** Source without comments, which quote widths and templates as prose. */
const PAGE_CODE = PAGE.replace(/\/\*[\s\S]*?\*\//g, "").replace(/(?<!:)\/\/[^\n]*/g, "");

/** Each `<Plot ... />` element's attribute text. */
const PLOTS = [...PAGE_CODE.matchAll(/<Plot\b([\s\S]*?)\/>/g)].map((m) => m[1]);

describe("/bb84 follows the shell's breakpoint", () => {
  it("asks lib/layout.ts whether the layout is narrow", () => {
    expect(PAGE_CODE).toMatch(
      /import \{[^}]*\buseNarrowLayout\b[^}]*\} from "\.\.\/lib\/layout"/);
    expect(PAGE_CODE).toMatch(/const narrow = useNarrowLayout\(\);/);
  });

  it("carries no breakpoint of its own", () => {
    // A second breakpoint a few pixels from the shell's would leave a band of
    // widths where the sidebar is gone and the grids are still desktop grids.
    expect(PAGE_CODE).not.toMatch(/matchMedia|max-width|min-width|innerWidth/);
    for (const n of [NARROW_LAYOUT_MAX_PX, NARROW_LAYOUT_MAX_PX + 1]) {
      expect(PAGE_CODE).not.toMatch(new RegExp(`(?<![\\w-])${n}(?!\\w)`));
    }
  });

  it("both grids are one column when narrow and the old two columns otherwise", () => {
    // Every template on the page, and each of them is the narrow switch.
    expect(PAGE_CODE.match(/gridTemplateColumns:/g)).toHaveLength(2);
    expect(PAGE_CODE.match(/gridTemplateColumns: narrowColumns\(narrow, "1fr 1fr"\)/g))
      .toHaveLength(2);
  });
});

describe("a card cannot widen its column", () => {
  it("ChartCard sets minWidth: 0, so a chart at a stale width cannot hold the track open", () => {
    const card = PAGE_CODE.slice(PAGE_CODE.indexOf("function ChartCard("));
    expect(card).toMatch(/<div style=\{\{[^}]*minWidth: 0/);
  });

  it("the engine stats <pre> scrolls inside its card", () => {
    expect(PAGE_CODE).toMatch(/<pre style=\{\{[^}]*overflowX: "auto", maxWidth: "100%"/);
  });

  it("the photon frames table sits in its own horizontal scroll box", () => {
    expect(PAGE_CODE).toMatch(
      /<div style=\{\{ overflowX: "auto", maxWidth: "100%" \}\}>\s*<table\b/);
  });
});

describe("the charts follow their column", () => {
  it("finds both charts", () => {
    // Guard the guard: a regex that matched nothing would pass the next test.
    expect(PLOTS).toHaveLength(2);
  });

  it("every chart resizes with the window and spreads the autosizing layout", () => {
    for (const attrs of PLOTS) {
      expect(attrs).toMatch(/\buseResizeHandler\b/);
      expect(attrs).toMatch(/\.\.\.plotLayout\b/);
      // A fixed width would undo both.
      expect(attrs).not.toMatch(/\bwidth:\s*\d/);
    }
    expect(PAGE_CODE).toMatch(/const plotLayout: any = \{\s*autosize: true,/);
  });

  it("the abort line's label is two lines when narrow and one line otherwise", () => {
    expect(PAGE_CODE).toMatch(/\(narrow \? "<br>" : " "\) \+ "\("/);
  });
});
