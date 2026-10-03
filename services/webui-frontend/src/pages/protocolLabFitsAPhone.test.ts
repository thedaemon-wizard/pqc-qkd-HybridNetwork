/**
 * /protocol-lab fits a phone, and is unchanged from 768px up.
 *
 * With the collapsed shell in place (lib/layout.ts) the page scrolled sideways
 * only in one state, but four things still did not fit. Measured on
 * 2026-09-26 in headless Chrome, walking every network and scenario with the
 * simulation running and a link down:
 *
 *   - A <select> is as wide as its longest option. The Tokyo scenario title
 *     made the Scenario select 343px: at 320px it ran 78px out of its 264px
 *     panel and scrolled the whole page 51px sideways, and at 375px it still
 *     ran 23px out of the panel.
 *   - The store-panel grid is `repeat(auto-fit, minmax(300px, 1fr))`. At 320px
 *     the content box is 288px, so its one column was 300px and every store
 *     panel ran 12px into the right gutter.
 *   - The links table has width: 100% inside its own scroll box, so on a phone
 *     the auto layout gave each column its min-content width. The Length and
 *     model columns became about 45px wide, one word per line: at 375px the
 *     tallest SECOQC row was 432px and Thuringia's 500px.
 *   - A downed link's gauge header shared one line between the link id and
 *     its rate, so at 320px both halves broke over two lines side by side.
 *
 * The fixes switch on the shell's one breakpoint and pass the old styles
 * through unchanged above it. At 768px and 1280px the page's screenshots are
 * pixel-identical to the baseline, and every element's box is the same in
 * every network and scenario.
 *
 * A second pass, measured on 2026-09-26: seventy-five "x" characters with no
 * break in them, put in place of each gauge's rate, ran to x = 476px at a
 * 320px viewport, 185px past its row (130px at 375px). The Q-buffer panel's
 * text may now break anywhere below 768px, and the same token stays inside
 * its row at 320 and 375px; today's rates, which have spaces, keep their 17px
 * rows. The links table's scroll box is now a ScrollRegion, which is named and
 * reachable by keyboard while the table is wider than it: below 768px, where
 * the table keeps an 800px minimum, and at 768px itself, where it is wider
 * than its box at its width of 100%. And the capped Scenario select showed
 * "Tokyo secure TV conference: attack an" at 320px, so on a phone it carries
 * the chosen title as its title.
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

import { NARROW_COLUMN, NARROW_LAYOUT_MAX_PX, NARROW_MAIN_PADDING } from "../lib/layout";
import { ProtocolLabSim, type ProtocolLabState } from "../lib/sim/protocolLabSim";
import { RunSeeds } from "../lib/sim/runSeed";
import LoadPresetDropdown from "../components/LoadPresetDropdown";
import QBufferGauge from "../components/QBufferGauge";
import { SCROLL_REGION_STYLE } from "../components/ScrollRegion";
import ProtocolLab from "./ProtocolLab";

const HERE = new URL(".", import.meta.url).pathname;
const read = (rel: string) => readFileSync(join(HERE, rel), "utf8");
/** Source without comments, which quote widths and templates as prose. */
const code = (src: string) => src.replace(/\/\*[\s\S]*?\*\//g, "").replace(/(?<!:)\/\/[^\n]*/g, "");

const FILES = {
  page: code(read("ProtocolLab.tsx")),
  presets: code(read("../components/LoadPresetDropdown.tsx")),
  gauge: code(read("../components/QBufferGauge.tsx")),
};

/** The narrowest phone the page is checked at, in CSS px. */
const NARROWEST_PHONE_PX = 320;
/** CSS px per rem: the app does not change the browser's root font size. */
const ROOT_FONT_PX = 16;

/** The store-panel grid's template from 768px up. */
const STORE_GRID = "repeat(auto-fit, minmax(300px, 1fr))";

beforeEach(() => { viewport.narrow = false; });

describe("/protocol-lab follows the shell's breakpoint", () => {
  it("asks lib/layout.ts whether the layout is narrow, in the page and its components", () => {
    for (const [name, src] of Object.entries(FILES)) {
      expect(src, name).toMatch(/import \{[^}]*\buseNarrowLayout\b[^}]*\} from "\.\.\/lib\/layout"/);
      expect(src, name).toMatch(/const narrow = useNarrowLayout\(\);/);
    }
  });

  it("carries no breakpoint of its own", () => {
    // A second breakpoint a few pixels from the shell's would leave a band of
    // widths where the sidebar is gone and a grid is still a desktop grid.
    for (const [name, src] of Object.entries(FILES)) {
      expect(src, name).not.toMatch(/matchMedia|max-width|min-width|innerWidth/);
      for (const n of [NARROW_LAYOUT_MAX_PX, NARROW_LAYOUT_MAX_PX + 1]) {
        expect(src, name).not.toMatch(new RegExp(`(?<![\\w-])${n}(?!\\w)`));
      }
    }
  });
});

describe("the store-panel grid", () => {
  it("passes its wide template through narrowColumns unchanged", () => {
    expect(FILES.page).toContain(`gridTemplateColumns: narrowColumns(narrow, "${STORE_GRID}")`);
  });

  it("keeps the auto-fit template from 768px up", () => {
    const html = renderToStaticMarkup(createElement(ProtocolLab));
    expect(html).toContain(`grid-template-columns:${STORE_GRID}`);
  });

  it("is one shrinkable column below 768px", () => {
    viewport.narrow = true;
    const html = renderToStaticMarkup(createElement(ProtocolLab));
    expect(html).toContain(`grid-template-columns:${NARROW_COLUMN}`);
    expect(html).not.toContain(`grid-template-columns:${STORE_GRID}`);
  });

  it("every other auto-fit minimum on the page fits the narrowest phone's content box", () => {
    // The KPI row keeps `minmax(150px, 1fr)` below the breakpoint: one card
    // across at 320px, two at 375px, none past the gutter. Raising a minimum
    // past the content box is how the 300px store grid overflowed.
    const gutter = parseFloat(NARROW_MAIN_PADDING) * ROOT_FONT_PX;
    expect(NARROW_MAIN_PADDING).toMatch(/^\d+(\.\d+)?rem$/);
    const contentBox = NARROWEST_PHONE_PX - 2 * gutter;
    const bare = [...FILES.page.matchAll(/gridTemplateColumns: "([^"]*)"/g)].map((m) => m[1]);
    expect(bare.length, "the KPI row's template").toBeGreaterThan(0);
    for (const t of bare) {
      for (const m of t.matchAll(/minmax\((\d+)px/g)) {
        expect(Number(m[1]), t).toBeLessThanOrEqual(contentBox);
      }
    }
  });
});

describe("the network and scenario selects", () => {
  const render = () => renderToStaticMarkup(createElement(LoadPresetDropdown, {
    presetId: "tokyo-2010", scenarioId: null, onChange: () => {},
  }));
  const selectStyles = (html: string) => [...html.matchAll(/<select[^>]*style="([^"]*)"/g)].map((m) => m[1]);
  const labelStyles = (html: string) => [...html.matchAll(/<label style="([^"]*)"/g)].map((m) => m[1]);

  it("size to their options from 768px up, beside their captions", () => {
    const html = render();
    expect(selectStyles(html)).toHaveLength(2);
    for (const s of selectStyles(html)) expect(s).not.toMatch(/width:100%/);
    for (const s of labelStyles(html)) expect(s).not.toMatch(/flex-direction/);
  });

  it("are as wide as the panel, under their captions, below 768px", () => {
    viewport.narrow = true;
    const html = render();
    expect(selectStyles(html)).toHaveLength(2);
    for (const s of selectStyles(html)) expect(s).toMatch(/width:100%;min-width:0/);
    for (const s of labelStyles(html)) {
      expect(s).toMatch(/flex-direction:column/);
      expect(s).toMatch(/min-width:0/);
    }
  });

  it("keep their accessible names in both layouts", () => {
    for (const narrow of [false, true]) {
      viewport.narrow = narrow;
      const html = render();
      expect(html).toContain('aria-label="Published network"');
      expect(html).toContain('aria-label="Cited scenario"');
    }
  });
});

describe("the Scenario select's title", () => {
  const TOKYO = "Tokyo secure TV conference: attack and switch-over";
  const render = (scenarioId: string | null) => renderToStaticMarkup(createElement(LoadPresetDropdown, {
    presetId: "tokyo-2010", scenarioId, onChange: () => {},
  }));
  const scenarioSelect = (html: string) => /<select aria-label="Cited scenario"[^>]*>/.exec(html)?.[0] ?? "";

  it("is the chosen scenario's full title, which the capped select cuts short on a phone", () => {
    viewport.narrow = true;
    expect(scenarioSelect(render("tokyo-reroute-2010"))).toContain(`title="${TOKYO}"`);
  });

  it("is 'Free play' when no scenario is chosen, the option the select shows", () => {
    viewport.narrow = true;
    const html = render(null);
    expect(scenarioSelect(html)).toContain('title="Free play"');
    expect(html).toContain('<option value="" selected="">Free play</option>');
  });

  it("is left out for a scenario id with no option, rather than guessed", () => {
    viewport.narrow = true;
    expect(scenarioSelect(render("no-such-scenario"))).not.toMatch(/title=/);
    // The same select with a known scenario does carry one, so the check
    // above is not passing for want of any title at all.
    expect(scenarioSelect(render("tokyo-reroute-2010"))).toMatch(/title=/);
  });

  it("is left out from 768px up, where the select is as wide as its longest option", () => {
    // No tooltip on hover and no second reading of the value as the select's
    // description: the select is exactly what it was before the narrow layout.
    for (const scenarioId of ["tokyo-reroute-2010", null]) {
      expect(scenarioSelect(render(scenarioId))).not.toMatch(/title=/);
    }
    expect(FILES.presets).toContain("title={narrow ? scenarioTitle : undefined}");
  });
});

describe("the links table", () => {
  const tableStyle = (html: string) => /<table style="([^"]*)"/.exec(html)?.[1] ?? "";
  /** Every attribute of the box the table sits in. */
  const box = (html: string) => /<div ([^>]*)><table/.exec(html)?.[1] ?? "";
  const BOX_STYLE = "overflow-x:auto;max-width:100%";

  it("sits in a ScrollRegion, not an ad hoc scroll box", () => {
    expect(SCROLL_REGION_STYLE).toEqual({ overflowX: "auto", maxWidth: "100%" });
    expect(FILES.page).toMatch(/<ScrollRegion aria-label="Links as published table">/);
    expect(FILES.page).not.toMatch(/overflowX: "auto"/);
  });

  it("renders in ScrollRegion's plain box on both sides of the breakpoint, where the #133 head had a bare overflowX box", () => {
    // A server render measures nothing. In the browser the box is a named
    // region while the table is wider than it: below 768px, and at 768px,
    // where the 100%-wide table is still wider than its box.
    for (const narrow of [false, true]) {
      viewport.narrow = narrow;
      expect(box(renderToStaticMarkup(createElement(ProtocolLab)))).toBe(`style="${BOX_STYLE}"`);
    }
  });

  it("gets a named minimum width only when narrow", () => {
    expect(FILES.page).toMatch(/const NARROW_LINKS_TABLE_MIN_PX = \d+;/);
    expect(FILES.page).toContain("minWidth: narrow ? NARROW_LINKS_TABLE_MIN_PX : undefined");
  });

  it("is laid out as before from 768px up", () => {
    const html = renderToStaticMarkup(createElement(ProtocolLab));
    expect(tableStyle(html)).toMatch(/width:100%/);
    expect(tableStyle(html)).not.toMatch(/min-width/);
  });

  it("scrolls inside its own box below 768px instead of squeezing its columns", () => {
    viewport.narrow = true;
    const html = renderToStaticMarkup(createElement(ProtocolLab));
    expect(tableStyle(html)).toMatch(/min-width:\d+px/);
  });
});

describe("the Q-buffer panel's text", () => {
  /** The attributes of the block right under the Q-buffer panel's heading. */
  const gaugeBlock = (html: string) =>
    /Link key stores \(Q-buffers\)<\/h3><div([^>]*)>/.exec(html)?.[1];

  it("may break a word anywhere below 768px, so an unbroken rate cannot leave its row", () => {
    // overflow-wrap is inherited, so this reaches the rate in QBufferGauge's
    // header row. "anywhere", because only it lowers min-content, which is
    // what lets the rate's flex item shrink to the row.
    viewport.narrow = true;
    expect(FILES.page).toMatch(/const NARROW_GAUGE_TEXT: CSSProperties = \{ overflowWrap: "anywhere" \};/);
    expect(gaugeBlock(renderToStaticMarkup(createElement(ProtocolLab)))).toBe(' style="overflow-wrap:anywhere"');
  });

  it("from 768px up is a plain block, as if it were not there", () => {
    // A div with no style, padding or border changes no box: the gauges'
    // margins collapse through it as they did through the panel.
    expect(gaugeBlock(renderToStaticMarkup(createElement(ProtocolLab)))).toBe("");
  });
});

describe("a Q-buffer gauge for a downed link", () => {
  function downedLinkState(): ProtocolLabState {
    let last!: ProtocolLabState;
    let n = 0;
    const sim = new ProtocolLabSim((s) => { last = s; }, {
      seeds: new RunSeeds(1), newKsid: () => `ksid-${++n}`, presetId: "cambridge-2019",
    });
    sim.injectFailure({ kind: "node", id: "TREL" });
    sim.dispose();
    return last;
  }
  const render = () => {
    const s = downedLinkState();
    const link = s.links.find((l) => l.down);
    expect(link, "a link is down").toBeDefined();
    return renderToStaticMarkup(createElement(QBufferGauge, {
      link: link!, accounting: s.accounting, keyBits: s.key_bits, scaleBits: null,
    }));
  };
  const headerStyle = (html: string) => /<div style="(display:flex;justify-content:space-between[^"]*)"/.exec(html)?.[1] ?? "";

  it("keeps the id and the rate on one line from 768px up", () => {
    const style = headerStyle(render());
    expect(style).not.toBe("");
    expect(style).not.toMatch(/flex-wrap/);
  });

  it("lets the rate drop under the id below 768px", () => {
    viewport.narrow = true;
    expect(headerStyle(render())).toMatch(/flex-wrap:wrap/);
  });
});
