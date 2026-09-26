/**
 * The saved-exports list opens inside the viewport.
 *
 * It hangs right-aligned under its button, and is wider than the space to the
 * button's left whenever the button sits near the left of the page. Measured
 * on 2026-09-26 on /pqc: the list started 109px left of the viewport at 375px
 * and 16px left of it at 768px, where no scrolling reaches. The component now
 * moves it back inside by the amount shiftIntoViewport returns, which is 0
 * where it already fits (at 1280px the same list sits 436px from the edge).
 */
import { describe, expect, it } from "vitest";

import { LIST_VIEWPORT_GUTTER_PX, shiftIntoViewport } from "./SavedExportsPicker";

const G = LIST_VIEWPORT_GUTTER_PX;

describe("shiftIntoViewport", () => {
  it("leaves a list that fits where it is", () => {
    expect(shiftIntoViewport(436, 814, 1280, G)).toBe(0);
    expect(shiftIntoViewport(G, 375 - G, 375, G)).toBe(0);
  });

  it("moves a list that starts left of the gutter to the gutter", () => {
    expect(shiftIntoViewport(-109, 234, 375, G)).toBe(G + 109);
    expect(shiftIntoViewport(-16, 362, 768, G)).toBe(G + 16);
  });

  it("moves a list that runs past the right gutter back inside it", () => {
    expect(shiftIntoViewport(100, 400, 375, G)).toBe(375 - G - 400);
  });

  it("aligns a list wider than the space to the left gutter, so its start is readable", () => {
    expect(shiftIntoViewport(50, 450, 375, G)).toBe(G - 50);
  });

  it("the gutter is the collapsed shell's 16px", () => {
    expect(G).toBe(16);
  });
});
