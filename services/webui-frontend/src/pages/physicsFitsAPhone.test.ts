/**
 * /physics fits a phone, and is unchanged from 768px up.
 *
 * Once the shell dropped its 220px sidebar below 768px (lib/layout.ts), the
 * page itself still had its desktop grids. Measured on 2026-09-26 with the
 * collapsed shell in place:
 *
 *   - The page scrolled sideways by 157px at 375px, 212px at 320px and 118px
 *     at 414px. The parameter groups stayed two across; each row's 120px
 *     number input does not shrink, and a bare `1fr` track is minmax(auto,
 *     1fr), so the tracks grew to fit label plus input and ran the right-hand
 *     column, with its inputs and backend buttons, past the screen.
 *   - The four key-rate cells would each be 47px inside their padding at
 *     375px, for values such as "1.262e-1" that are 60px in the cell's font.
 *   - The Optimize result is a 483px <pre> (its longest line is 83
 *     characters). At 375px it ran 124px past the screen.
 *
 * The fix is conditional on the one breakpoint: one group column and two
 * key-rate cells per row below 768px, the old templates, passed through
 * unchanged, above it. The <pre> is capped at its row's width and scrolls
 * inside itself; at 768px and 1280px it is 483px wide at the same place as
 * before. A fresh load at 1280px was pixel-identical to the baseline.
 *
 * The field reference table already sat in its own horizontal scroll box, so
 * it never widened the page; it is pinned here so it stays that way.
 */
import { describe, expect, it } from "vitest";

import { readFileSync } from "node:fs";
import { join } from "node:path";

import { NARROW_LAYOUT_MAX_PX } from "../lib/layout";

const HERE = new URL(".", import.meta.url).pathname;
const PAGE = readFileSync(join(HERE, "PhysicsParams.tsx"), "utf8");
const FIELD_REFERENCE = readFileSync(join(HERE, "../components/FieldReferencePanel.tsx"), "utf8");

/** Source without comments, which quote widths and templates as prose. */
function code(src: string): string {
  return src.replace(/\/\*[\s\S]*?\*\//g, "").replace(/(?<!:)\/\/[^\n]*/g, "");
}
const PAGE_CODE = code(PAGE);

describe("/physics follows the shell's breakpoint", () => {
  it("asks lib/layout.ts whether the layout is narrow", () => {
    expect(PAGE_CODE).toMatch(
      /import \{[^}]*\buseNarrowLayout\b[^}]*\} from "\.\.\/lib\/layout"/);
    expect(PAGE_CODE).toMatch(/const narrow = useNarrowLayout\(\);/);
  });

  it("calls the hook before the loading early return", () => {
    // A hook after `if (!fields) return` runs on some renders and not others,
    // which React rejects the moment the parameters arrive.
    const hook = PAGE_CODE.indexOf("useNarrowLayout();");
    const early = PAGE_CODE.indexOf("if (!fields) return");
    expect(early, "the early return is gone; revisit this test").toBeGreaterThan(-1);
    expect(hook).toBeGreaterThan(-1);
    expect(hook).toBeLessThan(early);
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

describe("the grids", () => {
  it("the parameter groups are one column when narrow and two otherwise", () => {
    expect(PAGE_CODE).toMatch(/gridTemplateColumns: narrowColumns\(narrow, "1fr 1fr"\)/);
  });

  it("the key-rate cells are two across when narrow and four otherwise", () => {
    expect(PAGE_CODE).toMatch(
      /gridTemplateColumns: narrow \? NARROW_KPI_TEMPLATE : "repeat\(4, 1fr\)"/);
    expect(PAGE_CODE).toMatch(/const NARROW_KPI_COLUMNS = 2;/);
    expect(PAGE_CODE).toContain(
      "const NARROW_KPI_TEMPLATE = `repeat(${NARROW_KPI_COLUMNS}, ${NARROW_COLUMN})`;");
    expect(PAGE_CODE).toMatch(
      /import \{[^}]*\bNARROW_COLUMN\b[^}]*\} from "\.\.\/lib\/layout"/);
  });
});

describe("wide content scrolls inside its own box", () => {
  it("the Optimize result is capped at its row and scrolls sideways", () => {
    const box = /const preBox: React\.CSSProperties = \{([^}]*)\};/.exec(PAGE_CODE)?.[1] ?? "";
    expect(box, "preBox is not a style object").not.toBe("");
    expect(box).toMatch(/maxWidth: "100%"/);
    expect(box).toMatch(/overflowX: "auto"/);
    expect(PAGE_CODE).toMatch(/<pre style=\{preBox\}>/);
  });

  it("the field reference table sits in a named ScrollRegion", () => {
    // 572px of table: it scrolls at 375px and at 768px (2026-09-26), so the
    // box has to be a named Tab stop while it does, not a bare overflow div.
    expect(code(FIELD_REFERENCE)).toMatch(/<ScrollRegion aria-label="Field reference table">\s*<table\b/);
    expect(code(FIELD_REFERENCE)).not.toMatch(/<div style=\{\{ overflowX: "auto" \}\}>/);
  });
});
