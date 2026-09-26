/**
 * The page must not scroll sideways. One CSS default made every route do it.
 *
 * `App.tsx` lays out the shell as `gridTemplateColumns: "220px 1fr"`. A grid
 * item's `min-width` defaults to `auto` -- "do not shrink below my content's
 * intrinsic width" -- so the `1fr` track grew to fit the widest thing in it.
 * On /console that is a <pre> of container logs with lines past 1400px.
 *
 * The <pre> already sets `overflow-x: auto` and could have scrolled itself.
 * It was never asked to: the track had widened to accommodate it first, so the
 * whole document scrolled instead.
 *
 * Measured on the deployed build at a 1280px viewport:
 *
 *     body.scrollWidth  1713
 *     window.innerWidth 1280      -> 433px of horizontal scroll
 *
 * `<main>` is shared by all fourteen routes, so the defect was global;
 * /console was just the page whose content was wide enough to expose it.
 * Found by measuring geometry in the browser rather than by reading the page,
 * which is the only way this shows up -- nothing about the source looks wrong.
 *
 * The second time was on a phone. At a 375x812 viewport (measured 2026-09-26,
 * release 0.1.0 and the branch after it) the 220px sidebar column stayed, so
 * <main> was 155px wide: 13 of 14 routes scrolled sideways, by 48px to 394px,
 * and /vpn wrapped ten text columns one character per line. At 768px and
 * 1280px no route overflowed. So below 768px the shell drops the sidebar
 * column for a top bar and a menu, and from 768px up it is the grid above,
 * unchanged. The breakpoint lives in lib/layout.ts, once.
 */
import { describe, expect, it } from "vitest";

import { readFileSync } from "node:fs";
import { join } from "node:path";

import { NARROW_LAYOUT_MAX_PX, NARROW_LAYOUT_QUERY } from "../lib/layout";

const HERE = new URL(".", import.meta.url).pathname;
const APP = readFileSync(join(HERE, "../App.tsx"), "utf8");

/** App.tsx without its comments, which quote widths and breakpoints as prose. */
const APP_CODE = APP.replace(/\/\*[\s\S]*?\*\//g, "").replace(/(?<!:)\/\/[^\n]*/g, "");

/** The body of a `const NAME: CSSProperties = { ... };` style object in App.tsx. */
function styleObject(name: string): string {
  const m = new RegExp(`const ${name}: CSSProperties = \\{([^;]*)\\};`).exec(APP_CODE);
  return m?.[1] ?? "";
}

describe("the shell lets its content column shrink", () => {
  it("main sets minWidth: 0", () => {
    expect(APP).toMatch(/<main\b[^>]*?style=\{\{[^}]*minWidth:\s*0/);
  });

  it("the grid track is still 1fr, so the fix is the min-width and not a cap", () => {
    // Capping the column at a pixel width would also stop the overflow, and
    // would stop the layout being responsive. Keep the reason honest.
    expect(APP).toMatch(/gridTemplateColumns:\s*"220px 1fr"/);
  });

  it("the reason is recorded next to it", () => {
    // A bare `minWidth: 0` reads as noise and gets deleted by the next person
    // tidying up. It is the whole fix.
    expect(APP).toMatch(/min-width defaults to `auto`|intrinsic width/);
  });
});

describe("below the breakpoint the shell is one column", () => {
  it("the 220px sidebar grid is the wide shell, used only when not narrow", () => {
    expect(styleObject("WIDE_SHELL")).toMatch(/gridTemplateColumns:\s*"220px 1fr"/);
    expect(APP_CODE).toMatch(/style=\{narrow \? NARROW_SHELL : WIDE_SHELL\}/);
    // One sidebar template, not a second copy with other numbers.
    expect(APP_CODE.match(/gridTemplateColumns/g)).toHaveLength(1);
  });

  it("the narrow shell is a single column with no sidebar track", () => {
    const narrow = styleObject("NARROW_SHELL");
    expect(narrow, "NARROW_SHELL is not a style object in App.tsx").not.toBe("");
    expect(narrow).toMatch(/flexDirection:\s*"column"/);
    expect(narrow).not.toMatch(/220|gridTemplateColumns/);
  });

  it("the narrow shell's <main> keeps minWidth: 0 and uses the named padding", () => {
    // The wide padding is the one <main> always had. outline: "none" is the
    // one addition at every width, and an outline takes no space; tabIndex
    // -1 only lets the shell move focus to <main> (lib/disclosure.test.ts).
    expect(APP_CODE).toMatch(
      /<main ref=\{mainRef\} tabIndex=\{-1\}\s*style=\{\{ padding: narrow \? NARROW_MAIN_PADDING : "1\.5rem 2rem", minWidth: 0, outline: "none" \}\}>/);
  });

  it("the breakpoint comes from NARROW_LAYOUT_MAX_PX, not a literal in App.tsx", () => {
    expect(APP_CODE).toMatch(/import \{[^}]*\buseNarrowLayout\b[^}]*\} from "\.\/lib\/layout"/);
    expect(APP_CODE).toMatch(/const narrow = useNarrowLayout\(\);/);
    expect(APP_CODE).not.toMatch(/matchMedia|max-width|min-width|innerWidth/);
    // As a number of its own: "ML-KEM-768" in the sidebar is an algorithm name.
    for (const n of [NARROW_LAYOUT_MAX_PX, NARROW_LAYOUT_MAX_PX + 1]) {
      expect(APP_CODE).not.toMatch(new RegExp(`(?<![\\w-])${n}(?!\\w)`));
    }
    expect(NARROW_LAYOUT_QUERY).toBe(`(max-width: ${NARROW_LAYOUT_MAX_PX}px)`);
  });

  it("the <main> element comes second in both layouts, so crossing the breakpoint keeps the page mounted", () => {
    // The sidebar (wide) or the top bar (narrow) is the first child and <main>
    // the second. Two separate returns would put <main> at a different place
    // in the tree and remount the page, losing a running simulation.
    expect(APP_CODE.match(/<main\b/g)).toHaveLength(1);
    expect(APP_CODE.match(/<Routes>/g)).toHaveLength(1);
  });
});
