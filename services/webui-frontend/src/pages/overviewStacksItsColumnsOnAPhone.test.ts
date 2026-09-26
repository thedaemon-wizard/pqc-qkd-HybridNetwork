/**
 * / puts its layer diagram and its container table side by side, and on a
 * phone that row did not fit.
 *
 * The grid was `gridTemplateColumns: "1fr 1fr"`. A bare `1fr` track is
 * `minmax(auto, 1fr)`, so it does not shrink below its content. Measured on
 * 2026-09-26 with the collapsed shell: at a 375px viewport the tracks came to
 * 200px + 182px in a 343px row and the page scrolled sideways by 39px, and at
 * 320px by 94px; the "Container Status" heading and the table's Status column
 * were what stuck out. At 768px and 1280px nothing overflowed.
 *
 * So below the shell's breakpoint the grid is one shrinkable column (from
 * lib/layout.ts, not a breakpoint of its own), and the table sits in a
 * ScrollRegion: a box that scrolls sideways by itself if the table is ever
 * wider than the phone, and while it does, a labelled region the keyboard can
 * reach. While the table fits the box is a plain div with no Tab stop. From
 * 768px up the template is the same "1fr 1fr" as before: measured on
 * 2026-09-26, / at 768px and 1280px is pixel for pixel what it is on the
 * branch before this change.
 *
 * The page is rendered with useNarrowLayout mocked, because a server render
 * has no viewport and always renders the wide layout. A server render also
 * runs no effects, so the box is ScrollRegion's plain div on both sides of
 * the breakpoint; whether it is a region is decided in the browser from its
 * widths (components/scrollRegionIsReachableWhileItScrolls.test.ts).
 * ExportToolbar is stubbed: it is not what these tests are about.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";

import { readFileSync } from "node:fs";
import { join } from "node:path";

import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";

const viewport = vi.hoisted(() => ({ narrow: false }));
vi.mock("../lib/layout", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../lib/layout")>()),
  useNarrowLayout: () => viewport.narrow,
}));
vi.mock("../components/ExportToolbar", () => ({ default: () => null }));

import Overview from "./Overview";

const HERE = new URL(".", import.meta.url).pathname;
/** Overview.tsx without its comments, which describe the widths in prose. */
const CODE = readFileSync(join(HERE, "Overview.tsx"), "utf8")
  .replace(/\/\*[\s\S]*?\*\//g, "").replace(/(?<!:)\/\/[^\n]*/g, "");

/** The name the table's box gives assistive technology while it scrolls. */
const TABLE_LABEL = "Container status table";
/** The markup React gives ScrollRegion's SCROLL_REGION_STYLE. */
const BOX_STYLE = "overflow-x:auto;max-width:100%";

function render(narrow: boolean): string {
  viewport.narrow = narrow;
  return renderToStaticMarkup(createElement(MemoryRouter, null, createElement(Overview)));
}

beforeEach(() => { viewport.narrow = false; });

describe("/ on a phone", () => {
  it("asks lib/layout.ts whether the layout is narrow", () => {
    expect(CODE).toMatch(/import \{[^}]*\bnarrowColumns\b[^}]*\buseNarrowLayout\b[^}]*\} from "\.\.\/lib\/layout"/);
    expect(CODE).toMatch(/const narrow = useNarrowLayout\(\);/);
  });

  it("the two-column grid is one column when narrow and unchanged otherwise", () => {
    expect(CODE).toMatch(/const OVERVIEW_WIDE_COLUMNS = "1fr 1fr";/);
    expect(CODE).toMatch(/gridTemplateColumns: narrowColumns\(narrow, OVERVIEW_WIDE_COLUMNS\)/);
    // No second, unconditional copy of the template left behind.
    expect(CODE).not.toMatch(/gridTemplateColumns: "1fr 1fr"/);
  });

  it("the container table is inside a labelled ScrollRegion, not a box of its own", () => {
    expect(CODE).toMatch(/import ScrollRegion from "\.\.\/components\/ScrollRegion";/);
    expect(CODE).toMatch(new RegExp(`<ScrollRegion aria-label="${TABLE_LABEL}">\\s*<table\\b`));
    // The page's own copy of the scroll style is gone; ScrollRegion owns it.
    expect(CODE).not.toMatch(/NARROW_TABLE_SCROLL/);
    expect(CODE).not.toMatch(/overflowX: "auto"/);
  });

  it("the table's box renders as ScrollRegion's plain div on both sides of the breakpoint", () => {
    // Plain until the browser measures the table wider than the box.
    for (const narrow of [false, true]) {
      const html = render(narrow);
      expect(html).toContain(`<div style="${BOX_STYLE}"><table`);
      expect(html).not.toMatch(/role="region"/);
      expect(html).not.toContain(TABLE_LABEL);
    }
  });

  it("the optional-row note may break its compose file name only when narrow", () => {
    expect(CODE).toMatch(/overflowWrap: narrow \? "anywhere" : undefined/);
  });
});
