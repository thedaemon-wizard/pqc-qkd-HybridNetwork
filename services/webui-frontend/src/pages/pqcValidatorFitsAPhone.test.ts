/**
 * /pqc fits a phone screen: the two result panels stack and a row's value may
 * drop below its label.
 *
 * Measured in headless Chrome on 2026-09-26 against a live backend, with the
 * collapsed shell from lib/layout already giving the page the whole screen.
 * On load the page fitted, because both result panels only said "Press Run".
 * After "Run round-trips", at a 375x812 viewport:
 *
 *     page overflow                        63px
 *     text one character per line          5 (every "✓ pass" verdict,
 *                                            a 9px-wide column 95px tall)
 *
 * Two things in this page did it. The KEM and signature panels were "1fr 1fr"
 * at every width, so each panel's rows were about 130px wide. And Row keeps
 * its label whole (flexShrink 0) and gives the value what is left, which a
 * value with overflowWrap "anywhere" accepts down to one character; the
 * longest liboqs label, kept whole, ran 42px past the screen's edge on its
 * own. After the change below the same run reads 0px and no character
 * columns at 320, 375, 414 and 600px. At 768 and 1280px the page on load is
 * pixel for pixel what it was, and after a run at 1280px only the live values
 * (timings, random hashes) differ.
 *
 * These tests pin the switch: which template the result grid gets on each
 * side of the breakpoint, and how a Row is styled on each side. The page reads
 * the breakpoint through useNarrowLayout, mocked here, because a server render
 * has no viewport and always renders the wide layout.
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
import PQCValidator, { Row } from "./PQCValidator";

const HERE = new URL(".", import.meta.url).pathname;
const SRC = readFileSync(join(HERE, "PQCValidator.tsx"), "utf8");
/** Source with its comments removed: what the page renders. */
const CODE = SRC.replace(/\/\*[\s\S]*?\*\//g, "").replace(/(?<!:)\/\/[^\n]*/g, "");

/** The longest label on the page, and the verdict that was squeezed beside it. */
const LONG_LABEL = "Shared secrets agree (liboqs encapsulated to this browser's key)";

function renderRow(): string {
  return renderToStaticMarkup(createElement(Row, { k: LONG_LABEL, v: "✓ pass" }));
}

/** The style attribute of the Row's outer div, label span and value span. */
function rowParts(html: string): { row: string; label: string; value: string } {
  const row = /<div style="(display:flex;[^"]*)">/.exec(html)?.[1] ?? "";
  const label = /<span style="(color:#9aa9d8;[^"]*)">/.exec(html)?.[1] ?? "";
  const value = /<span style="(font-family:monospace;[^"]*)">/.exec(html)?.[1] ?? "";
  return { row, label, value };
}

beforeEach(() => { viewport.narrow = false; });

describe("the result grid", () => {
  it("reads the shared breakpoint instead of carrying one of its own", () => {
    expect(SRC).toMatch(/import \{[^}]*\buseNarrowLayout\b[^}]*\} from "\.\.\/lib\/layout"/);
    expect(CODE).toMatch(/gridTemplateColumns:\s*narrowColumns\(narrow,\s*RESULT_COLUMNS\)/);
    expect(CODE).not.toMatch(/max-width|matchMedia|innerWidth/);
  });

  it("keeps the KEM and signature panels side by side from 768px up", () => {
    expect(CODE).toMatch(/const RESULT_COLUMNS = "1fr 1fr";/);
    const html = renderToStaticMarkup(createElement(PQCValidator));
    expect(html).toContain("grid-template-columns:1fr 1fr");
  });

  it("stacks them in one shrinkable column below 768px", () => {
    viewport.narrow = true;
    const html = renderToStaticMarkup(createElement(PQCValidator));
    expect(html).toContain(`grid-template-columns:${NARROW_COLUMN}`);
    expect(html).not.toContain("grid-template-columns:1fr 1fr");
  });

  it("has no two-column template left that ignores the breakpoint", () => {
    expect(CODE.match(/gridTemplateColumns/g)).toHaveLength(1);
  });
});

describe("a row", () => {
  it("from 768px up keeps its label whole and its value beside it, as before", () => {
    const { row, label, value } = rowParts(renderRow());
    expect(row, "Row's markup moved; this test is now vacuous").not.toBe("");
    expect(row).toContain("gap:12px");
    expect(row).not.toContain("flex-wrap");
    expect(label).toContain("flex-shrink:0");
    expect(value).toContain("min-width:0");
    expect(value).toContain("overflow-wrap:anywhere");
    expect(value).not.toContain("margin-left");
  });

  it("below 768px may put its value on the next line instead of squeezing it", () => {
    viewport.narrow = true;
    const { row, label, value } = rowParts(renderRow());
    expect(row).toContain("flex-wrap:wrap");
    // Still 12px between label and value on one line; only 2px when the value
    // moves to the line below, so it reads as that label's value: rows are
    // 6px apart (3px padding above and below), so the 2px has to stay smaller.
    expect(row).toContain("gap:2px 12px");
    expect(row).toContain("padding:3px 0");
    // A label wider than the whole row wraps between words rather than
    // running past the screen's edge.
    expect(label).toContain("flex-shrink:1");
    expect(value).toContain("min-width:0");
    expect(value).toContain("overflow-wrap:anywhere");
    // A value alone on its line stays on the right, where it is on one line.
    expect(value).toContain("margin-left:auto");
  });
});

describe("text this page does not control", () => {
  it("the liboqs response scrolls inside its own box and is never wider than its panel", () => {
    expect(CODE).toMatch(/const preBox: React\.CSSProperties = \{[^}]*overflowX: "auto", maxWidth: "100%"/);
    expect(CODE).toMatch(/<pre style=\{preBox\}>/);
  });

  it("an error's own text may break anywhere, so an unbroken path cannot widen the page", () => {
    expect(CODE).toMatch(/const errBox: React\.CSSProperties = \{[^}]*overflowWrap: "anywhere"/);
    expect(CODE).toMatch(/role="status" style=\{\{[^}]*overflowWrap: "anywhere"/);
  });
});
