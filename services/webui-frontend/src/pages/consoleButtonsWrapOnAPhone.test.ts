/**
 * /console has one button per container, six in a row about 330px wide.
 * Measured on 2026-09-26: at a 320px viewport the row ran past the right edge
 * and the page scrolled sideways by 27px. The row now wraps. From 375px up
 * the six fit on one row (measured at 768px and 1280px: one row, 22px tall),
 * so nothing moves there. The log <pre> already scrolls inside itself.
 */
import { describe, expect, it } from "vitest";

import { readFileSync } from "node:fs";
import { join } from "node:path";

const HERE = new URL(".", import.meta.url).pathname;
const CODE = readFileSync(join(HERE, "Console.tsx"), "utf8")
  .replace(/\/\*[\s\S]*?\*\//g, "").replace(/(?<!:)\/\/[^\n]*/g, "");

describe("/console on a phone", () => {
  it("the container buttons wrap instead of widening the page", () => {
    expect(CODE).toMatch(
      /<div style=\{\{ display: "flex", flexWrap: "wrap", gap: 8, marginBottom: 12 \}\}>\s*\{NAMES\.map\(/);
  });

  it("the log pane still scrolls inside itself", () => {
    expect(CODE).toMatch(/<pre style=\{\{[^}]*overflow: "auto", whiteSpace: "pre"/);
  });
});
