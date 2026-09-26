/**
 * /paper-flow fits a phone, and is unchanged from 768px up.
 *
 * Once the shell dropped its 220px sidebar below 768px (lib/layout.ts), the
 * page itself still had two grids sized for a desktop. Measured on 2026-09-26
 * in headless Chrome with the collapsed shell in place and the page's earlier
 * styles re-applied in the browser:
 *
 *   - The row of five KPI cards stayed five across. At 375px each card was
 *     59px and the labels broke inside words ("packe / ts", "hands / hake");
 *     at 320px all five labels were 22px wide, a few characters per line
 *     ("Pap / er / pac / kets").
 *   - The packet flow and failure cascade panels stayed side by side, 164px
 *     each at 375px. The packet table cannot wrap below 280px, so it ran out
 *     of its own panel and across the cascade panel next to it, and the
 *     cascade SVG was drawn 139px wide.
 *
 * Idle, neither showed up as page overflow, because the neighbouring panel
 * absorbed it; it showed up as squeezed text and one panel drawn over
 * another. With a run in progress at 320px and a five-digit byte total
 * (21326), the last KPI card's value ended at x=324 and the page scrolled
 * sideways by 4px; more as the total grows.
 *
 * The fix is conditional on the one breakpoint: two KPI cards per row, the
 * fifth spanning its row rather than sitting alone in half of it, and one
 * panel column below 768px; the old templates, passed through unchanged,
 * above it. The packet table also sits in its own horizontal scroll box, a
 * ScrollRegion, because at 320px the box is 263px and the table's narrowest
 * is 280px. That box is a named region the keyboard can reach while the table
 * is wider than it, and a plain div otherwise; a server render, which
 * measures nothing, is the plain div.
 */
import { afterEach, describe, expect, it, vi } from "vitest";

import { readFileSync } from "node:fs";
import { join } from "node:path";

import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";

const viewport = vi.hoisted(() => ({ narrow: false }));
vi.mock("../lib/layout", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../lib/layout")>()),
  useNarrowLayout: () => viewport.narrow,
}));

import { NARROW_LAYOUT_MAX_PX } from "../lib/layout";
import KPI from "../components/KPI";
import PacketFlowTable from "../components/PacketFlowTable";
import PaperDataExchange from "./PaperDataExchange";

const HERE = new URL(".", import.meta.url).pathname;
const PAGE = readFileSync(join(HERE, "PaperDataExchange.tsx"), "utf8");
const TABLE = readFileSync(join(HERE, "../components/PacketFlowTable.tsx"), "utf8");

/** Source without comments, which quote widths and templates as prose. */
function code(src: string): string {
  return src.replace(/\/\*[\s\S]*?\*\//g, "").replace(/(?<!:)\/\/[^\n]*/g, "");
}
const PAGE_CODE = code(PAGE);
const TABLE_CODE = code(TABLE);

describe("/paper-flow follows the shell's breakpoint", () => {
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

  it("every grid template on the page switches on `narrow`", () => {
    const templates = PAGE_CODE.match(/gridTemplateColumns:[^,\n]*/g) ?? [];
    expect(templates).toHaveLength(2);
    for (const t of templates) expect(t).toMatch(/\bnarrow\b/);
  });
});

describe("the KPI row is two cards across when narrow", () => {
  it("uses the narrow template below the breakpoint and five across above it", () => {
    expect(PAGE_CODE).toMatch(
      /gridTemplateColumns: narrow \? NARROW_KPI_TEMPLATE : "repeat\(5, 1fr\)"/);
  });

  it("the narrow template is two shrinkable columns, from named constants", () => {
    expect(PAGE_CODE).toMatch(/const NARROW_KPI_COLUMNS = 2;/);
    expect(PAGE_CODE).toContain(
      "const NARROW_KPI_TEMPLATE = `repeat(${NARROW_KPI_COLUMNS}, ${NARROW_COLUMN})`;");
    expect(PAGE_CODE).toMatch(
      /import \{[^}]*\bNARROW_COLUMN\b[^}]*\} from "\.\.\/lib\/layout"/);
  });

  it("the reason is recorded next to it", () => {
    expect(PAGE).toMatch(/labels broke inside words/);
  });
});

/**
 * The markup of each element directly inside the first element whose opening
 * tag starts with `open`, in order. Only for React's static markup, where
 * every tag is written out and closed.
 */
function directChildren(html: string, open: string): string[] {
  const start = html.indexOf(open);
  if (start < 0) return [];
  const tags = /<(\/?)([a-z0-9]+)[^>]*>/g;
  tags.lastIndex = html.indexOf(">", start) + 1;
  const kids: string[] = [];
  let depth = 0;
  let from = -1;
  for (let m = tags.exec(html); m; m = tags.exec(html)) {
    const closing = m[1] === "/";
    if (!closing && m[2] === "br") continue;
    if (!closing) {
      if (depth === 0) from = m.index;
      depth += 1;
    } else {
      if (depth === 0) break;
      depth -= 1;
      if (depth === 0) kids.push(html.slice(from, m.index + m[0].length));
    }
  }
  return kids;
}

describe("the fifth KPI card spans its row when narrow", () => {
  /** The label of the page's last KPI card. */
  const LAST = "Sim bytes accrued (per completed phase)";
  /** A KPI card's opening tag from 768px up, as KPI renders it. */
  const CARD_OPEN = /^<div style="[^"]*">/.exec(
    renderToStaticMarkup(createElement(KPI, { label: "x", value: 0 })))?.[0] ?? "<no card>";

  function render(narrow: boolean): string {
    viewport.narrow = narrow;
    return renderToStaticMarkup(createElement(PaperDataExchange));
  }
  afterEach(() => { viewport.narrow = false; });

  it("five cards in two columns leave one card over, and it is the last", () => {
    // If a card is added or the column count changes, the lone card is a
    // different one (or there is none), and the span below must be revisited.
    const cards = PAGE_CODE.match(/<KPI label=/g) ?? [];
    const columns = Number(/const NARROW_KPI_COLUMNS = (\d+);/.exec(PAGE_CODE)?.[1]);
    expect(cards).toHaveLength(5);
    expect(cards.length % columns).toBe(1);
    expect(PAGE_CODE).toMatch(
      /<FullRowWhenNarrow narrow=\{narrow\}>\s*<KPI label="Sim bytes accrued \(per completed phase\)"[\s\S]*?<\/FullRowWhenNarrow>\s*<\/div>/);
    expect(PAGE_CODE).toContain('const NARROW_FULL_ROW = "1 / -1";');
  });

  it("below 768px the last card sits in a grid item that spans every track", () => {
    const html = render(true);
    const spans = html.match(/grid-column:[^;"]*/g) ?? [];
    expect(spans).toEqual(["grid-column:1 / -1"]);
    // The spanning item holds the last card and nothing else.
    expect(html).toMatch(new RegExp(
      `<div style="grid-column:1 / -1"><div style="[^"]*"><div style="[^"]*">${LAST.replace(/[()]/g, "\\$&")}</div><div style="[^"]*">[^<]*</div></div></div>`));
  });

  it("from 768px up every card, the last one included, is a grid item of its own", () => {
    const html = render(false);
    expect(html).not.toContain("grid-column");
    // The KPI grid's direct children are the five cards themselves, the last
    // one the Sim bytes card: no wrapper sits between the grid and a card.
    const kids = directChildren(html, '<div style="display:grid;grid-template-columns:repeat(5, 1fr);');
    expect(kids).toHaveLength(5);
    for (const k of kids) expect(k.startsWith(CARD_OPEN), k.slice(0, 80)).toBe(true);
    expect(kids[4]).toContain(LAST);
  });
});

describe("the packet flow and cascade panels stack when narrow", () => {
  it("goes to one column below the breakpoint and keeps 1fr 1fr above it", () => {
    expect(PAGE_CODE).toMatch(/gridTemplateColumns: narrowColumns\(narrow, "1fr 1fr"\)/);
  });

  it("the packet table scrolls inside a named ScrollRegion, not the page", () => {
    // The region must be the table's parent, so the table scrolls inside it.
    expect(TABLE_CODE).toMatch(/import ScrollRegion from "\.\/ScrollRegion";/);
    expect(TABLE_CODE).toMatch(/<ScrollRegion aria-label="Packet flow table">\s*<table\b/);
    expect(TABLE_CODE).toMatch(/<\/table>\s*<\/ScrollRegion>\s*<\/Panel>/);
  });
});

describe("the packet table's box as rendered", () => {
  /** The markup React gives ScrollRegion's box style. */
  const BOX_STYLE = "overflow-x:auto;max-width:100%";

  function render(narrow: boolean): string {
    viewport.narrow = narrow;
    return renderToStaticMarkup(createElement(PacketFlowTable, { budgets: [], currentPhase: 0 }));
  }
  afterEach(() => { viewport.narrow = false; });

  it("below 768px is the same plain box until the browser measures the table wider than it", () => {
    const html = render(true);
    expect(html).toContain(`<div style="${BOX_STYLE}"><table`);
    expect(html).not.toMatch(/role=|tabindex=|aria-label=/i);
  });

  it("from 768px up is a plain scrolling div the #133 head did not have, as wide as the table there", () => {
    // At the #133 head the table sat directly in its panel. The box is as
    // wide as the panel's content and the table is 100% of it, so it changes
    // no width while the table fits.
    const html = render(false);
    expect(html).toMatch(/Evaluation Test 1\)<\/h3><div style="overflow-x:auto;max-width:100%"><table style="width:100%;/);
    expect(html).not.toMatch(/role=|tabindex=|aria-label=/i);
  });
});
