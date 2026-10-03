/**
 * /e2e must fit a phone without scrolling sideways.
 *
 * Measured on 2026-09-26 in headless Chrome with the collapsed shell already
 * in place (no sidebar below 768px) and the page's earlier styles re-applied
 * in the browser, idle and then with a run started from the page's own Run
 * button:
 *
 *     viewport   idle overflow   running overflow
 *       320px        179px            258px
 *       375px        123px            203px
 *       414px         85px            164px
 *       768px          0px             46px
 *
 * Four things did it, and each is pinned below:
 *
 *  1. The Run / Pause / ... / Step row had no flexWrap. Six buttons, the
 *     engine chip and the status badge need about 810px; the badge ended at
 *     x=578 on a 375px screen and at x=814 on a 768px one.
 *  2. The step strip and the KPI cards were four columns at every width, so
 *     on a phone each box was 71 to 102px wide and the rate card ended at
 *     x=377, past a 320px or a 375px screen.
 *  3. The two derived-material panels were side by side, 164px each at
 *     375px, and the PSK prefix wrapped one character per line beside its
 *     126px label, which Row keeps whole.
 *  4. The step-history table's detail column is up to 80 characters of JSON
 *     with no spaces. The UUID key_id values break only at their hyphens and
 *     step 3's 63-character detail has none, so the table's min-content width
 *     was 506px at every viewport width, and a bare <table> does not scroll
 *     itself: it ended at x=535 on a 375px screen.
 *
 * After the change: 0px at 320, 375, 414, 600, 768 and 1280, idle and
 * running. The table now scrolls in a ScrollRegion, 317px wide at 375px,
 * which is a named region the keyboard can reach while the table is wider
 * than it, at any width: with a run in progress that is up to 815px, where
 * the box is narrower than the table's 506px. The breakpoint is the shell's
 * (lib/layout.ts); this page has none of its own.
 */
import { afterEach, describe, expect, it, vi } from "vitest";

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

import { NARROW_COLUMN, narrowColumns } from "../lib/layout";
import QuantumSecureE2E from "./QuantumSecureE2E";

const HERE = new URL(".", import.meta.url).pathname;
const PAGE = readFileSync(join(HERE, "QuantumSecureE2E.tsx"), "utf8");

/** The page without its comments, which quote widths and templates as prose. */
const CODE = PAGE.replace(/\/\*[\s\S]*?\*\//g, "").replace(/(?<!:)\/\/[^\n]*/g, "");

/** The value of a top-level `const NAME = "...";` string constant in the page. */
function stringConst(name: string): string | undefined {
  return new RegExp(`const ${name} = "([^"]*)";`).exec(CODE)?.[1];
}

/** The body of function `name`, up to the next top-level function. */
function fnBody(name: string): string {
  const start = CODE.indexOf(`function ${name}(`);
  const next = CODE.indexOf("\nfunction ", start + 1);
  return start < 0 ? "" : CODE.slice(start, next < 0 ? undefined : next);
}

describe("/e2e follows the shell's breakpoint", () => {
  it("reads the narrow layout from lib/layout, and has no breakpoint of its own", () => {
    expect(CODE).toMatch(
      /import \{[^}]*\bnarrowColumns\b[^}]*\buseNarrowLayout\b[^}]*\} from "\.\.\/lib\/layout"/);
    expect(fnBody("QuantumSecureE2E")).toContain("const narrow = useNarrowLayout();");
    expect(CODE).not.toMatch(/matchMedia|max-width|min-width|innerWidth/);
  });
});

describe("the grids go to one column on a phone", () => {
  const GRIDS: [string, string][] = [
    ["STEP_STRIP_COLUMNS", "repeat(4, 1fr)"],
    ["KPI_COLUMNS", "repeat(4, 1fr)"],
    ["DERIVED_COLUMNS", "1fr 1fr"],
  ];

  it.each(GRIDS)("%s keeps its wide template and goes through narrowColumns", (name, wide) => {
    // The wide template is the one the page used before the breakpoint
    // existed, so the layout from 768px up is unchanged.
    expect(stringConst(name)).toBe(wide);
    expect(CODE).toContain(`gridTemplateColumns: narrowColumns(narrow, ${name})`);
    expect(narrowColumns(true, wide)).toBe(NARROW_COLUMN);
    expect(narrowColumns(false, wide)).toBe(wide);
  });

  it("no grid template is written inline any more", () => {
    // Every gridTemplateColumns in the page is one of the three above: a
    // fourth, inline, would be a grid that stays multi-column on a phone.
    const uses = CODE.match(/gridTemplateColumns:[^\n]*/g) ?? [];
    expect(uses).toHaveLength(GRIDS.length);
    for (const u of uses) expect(u).toMatch(/narrowColumns\(narrow, [A-Z_]+\)/);
  });
});

describe("rows that did not fit now wrap or scroll", () => {
  it("the operation controls row wraps", () => {
    // The row's style is the last style object before the Run button.
    const run = CODE.indexOf('ctl("start")');
    const rowStart = CODE.lastIndexOf("<div style={{", run);
    expect(run, "the Run button moved; this test is now vacuous").toBeGreaterThan(0);
    const rowStyle = CODE.slice(rowStart, CODE.indexOf("}}>", rowStart));
    expect(rowStyle).toMatch(/display: "flex"/);
    expect(rowStyle).toMatch(/flexWrap: "wrap"/);
  });

  it("the step-history table scrolls inside a named ScrollRegion", () => {
    expect(CODE).toMatch(/import ScrollRegion from "\.\.\/components\/ScrollRegion";/);
    expect(CODE).toMatch(
      /<ScrollRegion aria-label="Step history table">\s*<table style=\{\{ width: "100%"/);
    expect(CODE).toMatch(/<\/table>\s*<\/ScrollRegion>\s*<\/Panel>/);
  });

  it("the key/value row wraps its value below the label only in the narrow layout", () => {
    const row = fnBody("Row");
    expect(row, "Row moved; this test is now vacuous").not.toBe("");
    expect(row).toContain("const narrow = useNarrowLayout();");
    expect(row).toContain('...(narrow ? { flexWrap: "wrap" } : {})');
    // From 768px up the label stays whole and the gap is the old 12px.
    expect(row).toContain("flexShrink: narrow ? 1 : 0");
    expect(row).toMatch(/gap: narrow \? `\$\{NARROW_ROW_LINE_GAP_PX\}px \$\{ROW_GAP_PX\}px` : ROW_GAP_PX/);
    expect(CODE).toContain("const ROW_GAP_PX = 12;");
    expect(row).toContain('overflowWrap: "anywhere"');
  });
});

describe("the step-history box as rendered", () => {
  /** The page rendered on one side of the breakpoint (no effects run, so no run). */
  function render(narrow: boolean): string {
    viewport.narrow = narrow;
    return renderToStaticMarkup(createElement(MemoryRouter, null, createElement(QuantumSecureE2E)));
  }
  /** The markup React gives ScrollRegion's box style. */
  const BOX_STYLE = "overflow-x:auto;max-width:100%";

  afterEach(() => { viewport.narrow = false; });

  it("is ScrollRegion's plain box around the table on both sides of the breakpoint", () => {
    // A server render measures nothing, so the box is not yet a region; in
    // the browser it becomes one while the table is wider than it
    // (components/scrollRegionIsReachableWhileItScrolls.test.ts).
    for (const narrow of [false, true]) {
      const html = render(narrow);
      expect(html).toContain(`<div style="${BOX_STYLE}"><table`);
      expect(html).not.toMatch(/role="region"/);
    }
  });

  it("from 768px up is a box the #133 head did not have: there the table sat directly in its panel", () => {
    // The box is width-neutral while the table fits: it is exactly as wide as
    // the panel's content, and the table is 100% of it, as it was of the panel.
    const html = render(false);
    expect(html).toMatch(/Step history \(last 8\)<\/h3><div style="overflow-x:auto;max-width:100%"><table style="width:100%;/);
  });
});
