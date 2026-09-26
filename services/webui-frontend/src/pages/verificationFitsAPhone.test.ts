/**
 * /verify fits a phone screen: the liboqs matrix fits or scrolls inside its
 * own box, rows of four KPI cards become rows of two, and a Row table's label
 * column stops being 220px.
 *
 * Measured in headless Chrome on 2026-09-26 against a live backend, with the
 * collapsed shell from lib/layout already giving the page the whole screen:
 *
 *     viewport   page overflow
 *     320px      149px
 *     375px       95px
 *     414px       55px
 *
 * All of it was the crypto-agility matrix, a bare <table> of thirteen rows
 * whose narrowest possible width was 441px. liboqs names the SLH-DSA sets
 * like "SLH_DSA_PURE_SHA2_128S", one unbroken word that made the first column
 * 176px wide on its own. Two more things did not widen the page but did not
 * fit either: four KPI cards across left the rate "1.233e-2" 45px of card at
 * 375px, so it ran over the card's border, and at 320px the Row tables' 220px
 * label column left "HQC-1, HQC-3, HQC-5" a 45px column 110px tall.
 *
 * After the change below the page reads 0px of overflow at 320, 375, 414 and
 * 600px, on load and after the in-browser cross-check. At 768 and 1280px the
 * page on load is pixel for pixel what it was. A backend's error text, which
 * this page does not control, may also break anywhere, so an unbroken path in
 * it cannot widen the page.
 *
 * A second pass, measured on 2026-09-26 at 375px, dealt with what the first
 * left hard to read. The matrix fitted its 318px panel (301px at its
 * narrowest) only because its "sizes (B)" column shrank to 43px, and every KEM
 * cell broke over five or six lines, "pk" on one line and "1184" on the next.
 * Now each pair is a line of its own and never wraps. That column then needs
 * 62px and the table 325px at 4px side padding, 7px too wide, so the padding
 * went to 3px: the table is 315px at its narrowest, 318px wide at 375px,
 * fitting its panel, with rows 899px tall in all instead of 1188px. At 320px the panel has 263px, so the table
 * scrolls 52px inside its own box, a ScrollRegion, which the keyboard can
 * reach while the table is wider than it (and only then). And
 * "YES ✓" in the row of three KPI cards broke into "YES" over "✓" at 320px;
 * with a no-break space it stays on one line there.
 *
 * The page reads the breakpoint through useNarrowLayout, mocked here, because
 * a server render has no viewport and always renders the wide layout.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";

import { readFileSync } from "node:fs";
import { join } from "node:path";

import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";

const viewport = vi.hoisted(() => ({ narrow: false }));
vi.mock("../lib/layout", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../lib/layout")>()),
  useNarrowLayout: () => viewport.narrow,
}));

import { NARROW_COLUMN } from "../lib/layout";
import { SCROLL_REGION_STYLE } from "../components/ScrollRegion";
import { AgilityMatrix, Row } from "./Verification";

const HERE = new URL(".", import.meta.url).pathname;
const SRC = readFileSync(join(HERE, "Verification.tsx"), "utf8");
/** Source with its comments removed: what the page renders. */
const CODE = SRC.replace(/\/\*[\s\S]*?\*\//g, "").replace(/(?<!:)\/\/[^\n]*/g, "");

/** Two matrix rows as pqc-validator returns them: one hyphenated, one underscored. */
const MATRIX = [
  { algo: "ML-KEM-768", family: "KEM", enabled: true, ok: true, pk_len: 1184, ct_len: 1088, ss_len: 32 },
  { algo: "SLH_DSA_PURE_SHA2_128S", family: "SIG", enabled: true, ok: true, rejects_tampered: true,
    pk_len: 32, sig_len: 7856 },
];

function renderMatrix(): string {
  return renderToStaticMarkup(createElement(AgilityMatrix, { rows: MATRIX }));
}

/** The style attribute of every <th> and <td> in `html`. */
function cellStyles(html: string): string[] {
  return [...html.matchAll(/<t[hd] style="([^"]*)"/g)].map((m) => m[1]);
}

beforeEach(() => { viewport.narrow = false; });

/** The markup React gives SCROLL_REGION_STYLE. */
const SCROLL_BOX = "overflow-x:auto;max-width:100%";

/** The "sizes (B)" cell of the row whose algorithm is `algo`, as markup. */
function sizesCell(html: string, algo: string): string {
  const row = new RegExp(`<tr[^>]*><td[^>]*>${algo}</td>.*?</tr>`).exec(html)?.[0] ?? "";
  return /<td style="([^"]*font-family:monospace[^"]*)">(.*?)<\/td>/.exec(row)?.slice(1).join("|") ?? "";
}

describe("the liboqs matrix", () => {
  it("sits in a ScrollRegion: a box that scrolls sideways and is never wider than its panel", () => {
    expect(SCROLL_REGION_STYLE).toEqual({ overflowX: "auto", maxWidth: "100%" });
    expect(CODE).toMatch(/<ScrollRegion aria-label="PQC agility matrix">/);
    // No ad hoc scroll box is left beside it.
    expect(CODE).not.toMatch(/overflowX: "auto"/);
  });

  it("renders as ScrollRegion's plain box on both sides of the breakpoint", () => {
    // A server render measures nothing. In the browser the box becomes a
    // named region while the table is wider than it (at 320px, not at 375px),
    // which components/scrollRegionIsReachableWhileItScrolls.test.ts pins.
    for (const narrow of [false, true]) {
      viewport.narrow = narrow;
      expect(renderMatrix()).toMatch(new RegExp(`^<div style="${SCROLL_BOX}"><table `));
    }
  });

  it("from 768px up keeps its cells and algorithm names as they were", () => {
    const html = renderMatrix();
    const cells = cellStyles(html);
    expect(cells.length).toBeGreaterThan(0);
    for (const c of cells) expect(c).toMatch(/^padding:4px 8px/);
    expect(html).toContain(">SLH_DSA_PURE_SHA2_128S<");
    expect(html).not.toContain("<wbr");
  });

  it("below 768px has narrower cells and may break a name after an underscore", () => {
    viewport.narrow = true;
    expect(CODE).toMatch(/const NARROW_CELL_PAD_X_PX = 3;/);
    const html = renderMatrix();
    const cells = cellStyles(html);
    expect(cells.length).toBeGreaterThan(0);
    for (const c of cells) expect(c).toMatch(/^padding:4px 3px/);
    expect(html).toContain("SLH_<wbr/>DSA_<wbr/>PURE_<wbr/>SHA2_<wbr/>128S");
    // A hyphenated name already breaks after its hyphens; it is left alone.
    expect(html).toContain(">ML-KEM-768<");
  });

  it("the break opportunities add no characters: the name reads the same", () => {
    viewport.narrow = true;
    const text = renderMatrix().replace(/<wbr\/>/g, "");
    expect(text).toContain(">SLH_DSA_PURE_SHA2_128S<");
  });

  it("from 768px up writes the sizes on one line, joined by ' · ', as before", () => {
    const html = renderMatrix();
    expect(sizesCell(html, "ML-KEM-768")).toBe("padding:4px 8px;font-family:monospace|pk 1184 · ct 1088 · ss 32");
    expect(sizesCell(html, "SLH_DSA_PURE_SHA2_128S")).toBe("padding:4px 8px;font-family:monospace|pk 32 · sig 7856");
  });

  it("below 768px puts each size pair on a line of its own that does not wrap", () => {
    viewport.narrow = true;
    const html = renderMatrix();
    // nowrap keeps "pk" beside "1184"; the <br/> is the only place a line ends.
    expect(sizesCell(html, "ML-KEM-768"))
      .toBe("padding:4px 3px;font-family:monospace;white-space:nowrap|pk 1184<br/>ct 1088<br/>ss 32");
    const sig = /<tr[^>]*><td[^>]*>SLH_<wbr\/>DSA.*?<\/tr>/.exec(html)?.[0] ?? "";
    expect(sig, "the SIG row moved; this check is now vacuous").not.toBe("");
    expect(sig).toContain(">pk 32<br/>sig 7856</td>");
  });

  it("the narrow sizes add no characters: the same pairs, only the separator differs", () => {
    const pairs = (cell: string) => cell.split("|")[1].split(/<br\/>| · /);
    viewport.narrow = false;
    const wide = pairs(sizesCell(renderMatrix(), "ML-KEM-768"));
    viewport.narrow = true;
    const narrow = pairs(sizesCell(renderMatrix(), "ML-KEM-768"));
    expect(narrow).toEqual(wide);
    expect(wide).toEqual(["pk 1184", "ct 1088", "ss 32"]);
  });
});

describe("the rows of four KPI cards", () => {
  it("read the shared breakpoint instead of carrying one of their own", () => {
    expect(SRC).toMatch(/import \{[^}]*\buseNarrowLayout\b[^}]*\} from "\.\.\/lib\/layout"/);
    expect(CODE).not.toMatch(/max-width|matchMedia|innerWidth/);
  });

  it("are four across from 768px up and two across below it", () => {
    expect(CODE).toMatch(/const KPI_ROW_OF_FOUR = "repeat\(4, 1fr\)";/);
    expect(CODE).toMatch(/const NARROW_KPI_COLUMNS = 2;/);
    expect(CODE).toMatch(
      /const NARROW_KPI_TEMPLATE = `repeat\(\$\{NARROW_KPI_COLUMNS\}, \$\{NARROW_COLUMN\}\)`;/);
    // Both rows of four (key rate, packet budget) use the switch...
    expect(CODE.match(/gridTemplateColumns: narrow \? NARROW_KPI_TEMPLATE : KPI_ROW_OF_FOUR/g))
      .toHaveLength(2);
    // ...and no other four-across row is left that ignores it.
    expect(CODE.match(/repeat\(4, 1fr\)/g)).toHaveLength(1);
    expect(`repeat(2, ${NARROW_COLUMN})`).toBe("repeat(2, minmax(0, 1fr))");
  });

  it("the row of three keeps its template at every width", () => {
    // Measured: at 375px its labels and values fit three across. At 320px
    // "Algorithms exercised" breaks inside a word and "YES ✓" needs the
    // no-break space below; neither overflows the page.
    expect(CODE).toMatch(/gridTemplateColumns: "repeat\(3, 1fr\)"/);
  });
});

describe("the All pass KPI", () => {
  it("below 768px keeps 'YES ✓' on one line with a no-break space, and adds no glyph", () => {
    expect(SRC).toContain('const YES_KEPT_TOGETHER = "YES\\u00A0✓";');
    expect(CODE).toContain('value={agility.summary?.all_pass ? (narrow ? YES_KEPT_TOGETHER : "YES ✓") : "no"}');
    // The same characters as from 768px up, but for the one space.
    expect("YES\u00A0✓".replace("\u00A0", " ")).toBe("YES ✓");
  });
});

describe("text this page does not control", () => {
  it("a backend's error text may break anywhere, so an unbroken path cannot widen the page", () => {
    expect(CODE).toMatch(/role="status" style=\{\{[^}]*overflowWrap: "anywhere"/);
    expect(CODE).toMatch(/overflowWrap: "anywhere" \}\}>\s*TNO engine unavailable: \{keyrate\.error\}/);
  });
});

describe("a Row table", () => {
  const label = (html: string) => /<td style="([^"]*)">Our method<\/td>/.exec(html)?.[1] ?? "";
  const render = () => renderToStaticMarkup(
    createElement("table", null, createElement("tbody", null,
      createElement(Row, { k: "Our method", v: "Lo-Ma two-decoy asymptotic bound" }))));

  it("from 768px up keeps its 220px label column, which lines the tables up", () => {
    const style = label(render());
    expect(style, "Row's markup moved; this test is now vacuous").not.toBe("");
    expect(style).toContain("width:220px");
    expect(style).toMatch(/^padding:4px 8px/);
  });

  it("below 768px leaves the label column to the table's own layout", () => {
    viewport.narrow = true;
    const style = label(render());
    expect(style).not.toBe("");
    expect(style).not.toContain("width");
    // The narrow cells' padding, shared with the matrix.
    expect(style).toMatch(/^padding:4px 3px/);
  });
});
