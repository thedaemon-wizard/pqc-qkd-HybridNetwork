/**
 * /hil step 2 prints the KMS_URL template as one <code> run with no break
 * point in it. Measured on 2026-09-26: at a 320px viewport that run was 293px
 * wide in a list item about 248px wide, and the page scrolled sideways by
 * 29px. It now carries `overflow-wrap: anywhere`, which breaks it only when it
 * cannot fit on a line of its own; from 375px up it fits, so it renders as
 * before. Re-measured on 2026-09-26 with the style switched off in the page:
 * the run is 293px, and at 320px the page grew to 349px.
 *
 * The style's declaration sits above the page's doc comment, so that comment
 * stays attached to the component it describes.
 */
import { describe, expect, it } from "vitest";

import { readFileSync } from "node:fs";
import { join } from "node:path";

const HERE = new URL(".", import.meta.url).pathname;
const SRC = readFileSync(join(HERE, "HIL.tsx"), "utf8");
const CODE = SRC.replace(/\/\*[\s\S]*?\*\//g, "").replace(/(?<!:)\/\/[^\n]*/g, "");

describe("/hil on a phone", () => {
  it("the unbreakable-token style is overflow-wrap: anywhere", () => {
    expect(CODE).toMatch(/const UNBREAKABLE_TOKEN: React\.CSSProperties = \{ overflowWrap: "anywhere" \};/);
  });

  it("the KMS_URL template uses it", () => {
    expect(CODE).toMatch(/<code style=\{UNBREAKABLE_TOKEN\}>KMS_URL=/);
  });

  it("the page's doc comment directly precedes the component, with no other block between", () => {
    // One /** ... */ block, containing no other "*/", then the component.
    expect(SRC).toMatch(
      /\/\*\*\n \* Hardware-In-The-Loop bridge(?:(?!\*\/)[\s\S])*\*\/\nexport default function HIL\(\)/);
    const style = SRC.indexOf("const UNBREAKABLE_TOKEN");
    const doc = SRC.indexOf(" * Hardware-In-The-Loop bridge");
    // Both present, or the order below would compare against -1 and pass.
    expect(style).toBeGreaterThanOrEqual(0);
    expect(doc).toBeGreaterThanOrEqual(0);
    expect(style).toBeLessThan(doc);
  });
});
