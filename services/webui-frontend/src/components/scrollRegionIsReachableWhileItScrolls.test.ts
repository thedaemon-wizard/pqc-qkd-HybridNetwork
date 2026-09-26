/**
 * ScrollRegion: a box that scrolls its content sideways, and while it does, a
 * named region the keyboard can reach.
 *
 * Pages wrap a table or a chart that can be wider than its column in it, so
 * the content scrolls inside the box and not the page. The first version made
 * the box a region below 768px and a plain div from 768px up. Measured on
 * 2026-09-26 that was wrong both ways: at 768px the /e2e step-history table
 * (with a run in progress) and the Protocol Lab links table scrolled inside
 * boxes the keyboard could not reach, and at 375px four boxes whose content
 * fitted were Tab stops that did nothing. Now the box is a region exactly
 * while its content is wider than it, at any width.
 *
 * The decision is made in the browser from measured widths, so it is tested
 * here as the pure functions it is built from (scrollsSideways,
 * scrollRegionAttributes) and the watcher that keeps it current
 * (watchSideScroll), driven with fake observers. A server render runs no
 * effects and has nothing to measure: it is the plain box.
 */
import { describe, expect, it, vi } from "vitest";

import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";

import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";

import ScrollRegion, {
  SCROLL_REGION_STYLE, SUBPIXEL_OVERFLOW_PX, scrollRegionAttributes, scrollsSideways, watchSideScroll,
  type ScrollRegionProps, type SideScrollObservers,
} from "./ScrollRegion";

const HERE = new URL(".", import.meta.url).pathname;
/** ScrollRegion.tsx without its comments, which describe the observers in prose. */
const CODE = readFileSync(join(HERE, "ScrollRegion.tsx"), "utf8")
  .replace(/\/\*[\s\S]*?\*\//g, "").replace(/(?<!:)\/\/[^\n]*/g, "");

const LABEL = "Container status table";
/** The markup React gives SCROLL_REGION_STYLE. */
const BOX_STYLE = "overflow-x:auto;max-width:100%";

function render(props: Partial<Pick<ScrollRegionProps, "style" | "aria-describedby">> = {}): string {
  return renderToStaticMarkup(createElement(ScrollRegion,
    { "aria-label": LABEL, children: createElement("table"), ...props }));
}

describe("the box", () => {
  it("scrolls sideways and stays inside its column", () => {
    expect(SCROLL_REGION_STYLE).toEqual({ overflowX: "auto", maxWidth: "100%" });
  });
});

describe("whether the box scrolls sideways", () => {
  it("allows one pixel of rounding, and no more", () => {
    // Chrome reads a fraction of a pixel of overflow as one whole pixel.
    expect(SUBPIXEL_OVERFLOW_PX).toBe(1);
  });

  it("is false while the content fits, exactly or to within the rounding", () => {
    expect(scrollsSideways(343, 343)).toBe(false);
    expect(scrollsSideways(344, 343)).toBe(false);
    expect(scrollsSideways(280, 318)).toBe(false);
  });

  it("is true once the content is wider than that", () => {
    expect(scrollsSideways(345, 343)).toBe(true);
    // Measured 2026-09-26: /e2e's step history at 768px with a run going,
    // and the /keyflow chart in its 343px box at 375px.
    expect(scrollsSideways(506, 458)).toBe(true);
    expect(scrollsSideways(800, 343)).toBe(true);
  });
});

describe("the attributes", () => {
  const html = (attrs: object) => renderToStaticMarkup(createElement("div", attrs));

  it("while the box scrolls: a named region the keyboard can reach", () => {
    expect(html(scrollRegionAttributes(true, LABEL)))
      .toBe(`<div role="region" tabindex="0" aria-label="${LABEL}"></div>`);
  });

  it("while it scrolls, a description goes with the name", () => {
    expect(html(scrollRegionAttributes(true, LABEL, "hint")))
      .toBe(`<div role="region" tabindex="0" aria-label="${LABEL}" aria-describedby="hint"></div>`);
  });

  it("while it does not: no role, no Tab stop, no name and no description", () => {
    // No tabIndex: a stop that scrolls nothing is noise. aria-label is not
    // allowed on a div without a role.
    expect(scrollRegionAttributes(false, LABEL)).toEqual({});
    expect(scrollRegionAttributes(false, LABEL, "hint")).toEqual({});
  });
});

/** A node the fake observers can watch: the widths and the first element child. */
class FakeNode {
  scrollWidth = 0;
  clientWidth = 0;
  firstElementChild: FakeNode | null = null;
  constructor(readonly name: string) {}
}

/** Fake observers that record what they watch and let the test fire them. */
function fakeObservers() {
  const log: string[] = [];
  let resized = () => {};
  let childrenChanged = () => {};
  const observers: SideScrollObservers<FakeNode> = {
    resize(onResize) {
      resized = onResize;
      return {
        observe: (n) => { log.push(`resize.observe ${n.name}`); },
        unobserve: (n) => { log.push(`resize.unobserve ${n.name}`); },
        disconnect: () => { log.push("resize.disconnect"); },
      };
    },
    childList(onChange) {
      childrenChanged = onChange;
      return {
        observe: (n, options) => { log.push(`childList.observe ${n.name} ${JSON.stringify(options)}`); },
        disconnect: () => { log.push("childList.disconnect"); },
      };
    },
  };
  return { log, observers, resize: () => resized(), changeChildren: () => childrenChanged() };
}

/** A box holding one table, laid out at `content` px in a `box` px box. */
function boxWith(content: number, box: number): { box: FakeNode; table: FakeNode } {
  const b = new FakeNode("box");
  const table = new FakeNode("table");
  b.firstElementChild = table;
  b.scrollWidth = Math.max(content, box);
  b.clientWidth = box;
  return { box: b, table };
}

describe("watching the box", () => {
  it("watches the box and its content for size, and the box's own children, not its subtree", () => {
    const { box } = boxWith(318, 318);
    const f = fakeObservers();
    watchSideScroll(box, () => {}, f.observers);
    expect(f.log).toEqual([
      "resize.observe box",
      "resize.observe table",
      'childList.observe box {"childList":true}',
    ]);
  });

  it("answers once at the start, before any observer fires", () => {
    const answers: boolean[] = [];
    const { box } = boxWith(800, 343);
    watchSideScroll(box, (s) => answers.push(s), fakeObservers().observers);
    expect(answers).toEqual([true]);
  });

  it("follows a resize both ways, and reports only a change", () => {
    const answers: boolean[] = [];
    const { box } = boxWith(458, 458);
    const f = fakeObservers();
    watchSideScroll(box, (s) => answers.push(s), f.observers);
    // Rows arrive with a run: the table grows past the box.
    box.scrollWidth = 506;
    f.resize();
    f.resize();
    // The viewport widens to where the table fits again.
    box.clientWidth = 506;
    box.scrollWidth = 506;
    f.resize();
    expect(answers).toEqual([false, true, false]);
  });

  it("moves the resize watch to new content that replaces the old", () => {
    const answers: boolean[] = [];
    const { box } = boxWith(318, 318);
    const f = fakeObservers();
    watchSideScroll(box, (s) => answers.push(s), f.observers);
    box.firstElementChild = new FakeNode("wider");
    box.scrollWidth = 600;
    f.changeChildren();
    expect(f.log.slice(3)).toEqual(["resize.unobserve table", "resize.observe wider"]);
    // And it measures the new content at once.
    expect(answers).toEqual([false, true]);
  });

  it("leaves the watch alone when the children change but the first one does not", () => {
    const { box } = boxWith(318, 318);
    const f = fakeObservers();
    watchSideScroll(box, () => {}, f.observers);
    f.changeChildren();
    expect(f.log).toHaveLength(3);
  });

  it("stops both observers when the box goes away", () => {
    const { box } = boxWith(318, 318);
    const f = fakeObservers();
    const stop = watchSideScroll(box, () => {}, f.observers);
    stop();
    expect(f.log.slice(3)).toEqual(["resize.disconnect", "childList.disconnect"]);
  });
});

describe("the component", () => {
  it("watches its own box with the browser's observers, and stops on unmount", () => {
    expect(CODE).toMatch(/resize: \(onResize\) => new ResizeObserver\(onResize\)/);
    expect(CODE).toMatch(/childList: \(onChange\) => new MutationObserver\(onChange\)/);
    // The effect returns watchSideScroll's stop function as its cleanup, and
    // runs again only when the box element itself changes.
    expect(CODE).toMatch(
      /useClientLayoutEffect\(\(\) => \{[\s\S]*?return watchSideScroll<Element>\(box, setScrolls, BROWSER_OBSERVERS\);\s*\}, \[box\]\);/);
    expect(CODE).toMatch(/<div ref=\{ref\} \{\.\.\.scrollRegionAttributes\(scrolls, label, describedBy\)\} style=\{box\}>/);
  });

  it("measures before the first paint in the browser, without a layout effect in a server render", () => {
    expect(CODE).toContain('const useClientLayoutEffect = typeof window === "undefined" ? useEffect : useLayoutEffect;');
  });

  it("does not ask the viewport: the rule is the same at every width", () => {
    expect(CODE).not.toMatch(/useNarrowLayout|matchMedia|innerWidth/);
  });
});

describe("a server render", () => {
  it("is the plain box, with nothing measured yet", () => {
    expect(render()).toBe(`<div style="${BOX_STYLE}"><table></table></div>`);
    expect(render({ "aria-describedby": "hint" })).toBe(`<div style="${BOX_STYLE}"><table></table></div>`);
  });

  it("logs nothing: React 18 warns about a layout effect there, and there is none", () => {
    const errors = vi.spyOn(console, "error").mockImplementation(() => {});
    try {
      render();
      expect(errors).not.toHaveBeenCalled();
    } finally {
      errors.mockRestore();
    }
  });
});

describe("the style prop", () => {
  it("adds to the box", () => {
    expect(render({ style: { marginTop: 8 } })).toContain(`style="margin-top:8px;${BOX_STYLE}"`);
  });

  it("cannot replace overflowX or maxWidth", () => {
    expect(render({ style: { overflowX: "visible", maxWidth: 900 } })).toContain(`style="${BOX_STYLE}"`);
  });
});

/** Every .tsx file under src/, but this component's own. */
function sourcesUsingTheBox(): [string, string][] {
  const src = join(HERE, "..");
  return readdirSync(src, { recursive: true, encoding: "utf8" })
    .filter((f) => f.endsWith(".tsx") && !f.endsWith("ScrollRegion.tsx"))
    .map((f): [string, string] => [f, readFileSync(join(src, f), "utf8")])
    .filter(([, code]) => code.includes("<ScrollRegion"));
}

describe("the label", () => {
  it("every page that wraps wide content in a ScrollRegion names it", () => {
    // A string that is not empty, or a named constant. The pages that use it
    // today: /, /e2e, /paper-flow (the packet table), /verify,
    // /protocol-lab, /keyflow and /vpn.
    const uses = sourcesUsingTheBox().flatMap(([file, code]) =>
      [...code.matchAll(/<ScrollRegion\b([^>]*)>/g)].map((m) => [file, m[1]] as const));
    expect(uses.length).toBeGreaterThanOrEqual(7);
    for (const [file, attrs] of uses) {
      expect(attrs, file).toMatch(/\baria-label=(?:"[^"]*\S[^"]*"|\{[A-Z][A-Z0-9_]*\})/);
    }
  });

  it("is a required prop", () => {
    // @ts-expect-error: a ScrollRegion without an aria-label does not typecheck.
    const unnamed: ScrollRegionProps = { children: null };
    expect(unnamed).toBeDefined();
  });
});
