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
 * `<main>` is shared by all thirteen routes, so the defect was global;
 * /console was just the page whose content was wide enough to expose it.
 * Found by measuring geometry in the browser rather than by reading the page,
 * which is the only way this shows up -- nothing about the source looks wrong.
 */
import { describe, expect, it } from "vitest";

import { readFileSync } from "node:fs";
import { join } from "node:path";

const HERE = new URL(".", import.meta.url).pathname;
const APP = readFileSync(join(HERE, "../App.tsx"), "utf8");

describe("the shell lets its content column shrink", () => {
  it("main sets minWidth: 0", () => {
    expect(APP).toMatch(/<main style=\{\{[^}]*minWidth:\s*0/);
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
