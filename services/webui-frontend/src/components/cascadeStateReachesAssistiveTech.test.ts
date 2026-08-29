/**
 * The failure banner was drawn where assistive technology cannot reach it.
 *
 * `MultiHopTopologySvg` renders `role="img"`, which makes the element a LEAF
 * to a screen reader: every `<text>` inside is skipped and only the label is
 * announced. Measured on the deployed build with a qkd failure armed --
 * 126 text nodes in the SVG, the banner among them reading
 *
 *     "qkd failure -- 7-stage cascade (armed; press Run)"
 *
 * and the accessible name offering only "Multi-hop trusted-node topology
 * (Spooren et al. arXiv:2604.05599)". The state was on screen and nowhere else.
 *
 * Checklist row 4.4b.5 asks for that banner precisely because "a red bar with
 * no motion and no explanation is not acceptable feedback". For a non-visual
 * user there was no explanation at all -- the same complaint, one step along.
 *
 * The fix is the label, not the role. Dropping `role="img"` would expose 126
 * unordered coordinates-and-abbreviations text nodes, which is worse than a
 * summary.
 */
import { describe, expect, it } from "vitest";

import { readFileSync } from "node:fs";
import { join } from "node:path";

const SRC = readFileSync(
  join(new URL(".", import.meta.url).pathname, "MultiHopTopologySvg.tsx"), "utf8");

describe("the accessible name carries the failure state", () => {
  it("the label is computed, not a constant", () => {
    // A string literal cannot vary with the injected layer.
    expect(SRC).toMatch(/aria-label=\{/);
    expect(SRC, "the label went back to a fixed string")
      .not.toMatch(/aria-label="Multi-hop trusted-node topology[^"]*"\s*>/);
  });

  it("it names the layer, the cascade length and whether it is armed", () => {
    const i = SRC.indexOf("aria-label={");
    const label = SRC.slice(i, SRC.indexOf("}>", i));
    expect(label).toContain("failureLayer");
    expect(label).toContain("cascadeStages");
    expect(label).toMatch(/armed/);
  });

  it("it still names the subject when nothing has failed", () => {
    const i = SRC.indexOf("aria-label={");
    const label = SRC.slice(i, SRC.indexOf("}>", i));
    expect(label).toContain("Multi-hop trusted-node topology");
    // The failure clause must be conditional; an unconditional suffix would
    // announce a failure on a healthy diagram.
    expect(label).toMatch(/failureLayer\s*\n?\s*\?/);
  });

  it("role=img stays -- exposing 126 raw text nodes is worse than a summary", () => {
    expect(SRC).toMatch(/role="img"/);
  });

  it("the on-screen banner is unchanged", () => {
    // The fix adds a channel; it must not quietly alter what sighted users see.
    expect(SRC).toMatch(/\(armed; press Run\)/);
    expect(SRC).toMatch(/-stage cascade/);
  });
});
