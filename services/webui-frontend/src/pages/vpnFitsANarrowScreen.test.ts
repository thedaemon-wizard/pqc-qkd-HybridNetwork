/**
 * /vpn fits a phone screen: the lanes stack and a row's value may drop below
 * its label.
 *
 * Measured in headless Chrome on 2026-09-26 against a live backend. With the
 * 220px sidebar at a 375x812 viewport the page scrolled sideways by 232px and
 * wrapped ten values one character per line. The collapsed shell (lib/layout)
 * gave the page the whole screen, and /vpn still failed on its own:
 *
 *     viewport   page overflow   text one or two characters per line
 *     320px      51px            10 (the IPsec proposal string 570px tall)
 *     375px       4px            10
 *     414px       0px             2
 *
 * Two things in this page did it. The lane grid was "1fr 1fr" at every width,
 * so at 320px each panel row was about 100px wide, narrower than the label
 * "PPK required, both ends" (147px) on its own. And Row keeps its label whole
 * (flexShrink 0) and gives the value what is left, which a value with
 * overflowWrap "anywhere" accepts down to one character. After the change
 * below, the same measurement reads 0px and no character columns at 320, 375,
 * 414 and 600px, and at 768 and 1280px every element of the page sits where
 * it did before, apart from the width of live values such as "32s ago".
 *
 * These tests pin the switch: which template the lane grid gets on each side
 * of the breakpoint, and how a Row is styled on each side. The page reads the
 * breakpoint through useNarrowLayout, mocked here, because a server render has
 * no viewport and always renders the wide layout.
 *
 * Two narrow-only refinements, measured in headless Chrome 152 on 2026-09-26,
 * are pinned below too. The IPsec proposal, one unbroken word to the line
 * breaker, broke mid-name at 320px and left a lone "K" on its last line at
 * 375px; it now has a break opportunity after every "/". And the notes <pre>
 * under the lanes, 570px wide, scrolls inside a 313px box at 375px: Chrome
 * reached it with Tab, but as a "generic" stop named by its whole
 * 2,157-character text, so on a phone it now scrolls inside a ScrollRegion,
 * with a little side padding so its text clears the focus ring. From 768px up
 * both render exactly as before in a server render; in the browser the <pre>
 * there also takes the region's role, Tab stop and name while it scrolls
 * (it does at 768px), which changes no box.
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
import VpnProtocols, { IpsecProposal, WgInterface } from "./VpnProtocols";

const HERE = new URL(".", import.meta.url).pathname;
const SRC = readFileSync(join(HERE, "VpnProtocols.tsx"), "utf8");
/** Source with its comments removed: what the page renders. */
const CODE = SRC.replace(/\/\*[\s\S]*?\*\//g, "").replace(/(?<!:)\/\/[^\n]*/g, "");

/** One WireGuard interface as the backend returns it, with a long writer name. */
const WG = {
  name: "wireguard", status: "established", active_sa: 1, peers_fresh: 1,
  fresh_within_s: 180, peers: 1, peers_with_psk: 1, last_handshake: "12s ago",
  last_handshake_s: 12, proposal: null, psk_source: "arnika: HKDF-SHA3-256(QKD || PQC-HPKE)",
};

/** The style attribute of every Row's outer div (the flex rows with a 13px font). */
function rowStyles(html: string): string[] {
  return [...html.matchAll(/<div style="(display:flex;[^"]*font-size:13px[^"]*)">/g)].map((m) => m[1]);
}

/** The style attribute of every Row's label span (the one before the value). */
function labelStyles(html: string): string[] {
  return [...html.matchAll(/<span style="(color:#9aa9d8;flex-shrink:[^"]*)">/g)].map((m) => m[1]);
}

/** The style attribute of every Row's value span. */
function valueStyles(html: string): string[] {
  return [...html.matchAll(/<span style="(font-family:monospace;[^"]*)">/g)].map((m) => m[1]);
}

describe("the lane grid", () => {
  it("reads the shared breakpoint instead of carrying one of its own", () => {
    expect(SRC).toMatch(/import \{[^}]*\buseNarrowLayout\b[^}]*\} from "\.\.\/lib\/layout"/);
    expect(CODE).toMatch(/gridTemplateColumns:\s*narrowColumns\(narrow,\s*LANE_COLUMNS\)/);
    expect(CODE).not.toMatch(/max-width|matchMedia|innerWidth/);
  });

  it("keeps its two columns from 768px up", () => {
    expect(CODE).toMatch(/const LANE_COLUMNS = "1fr 1fr";/);
    viewport.narrow = false;
    const html = renderToStaticMarkup(createElement(VpnProtocols));
    expect(html).toContain("grid-template-columns:1fr 1fr");
  });

  it("stacks the lanes in one shrinkable column below 768px", () => {
    viewport.narrow = true;
    const html = renderToStaticMarkup(createElement(VpnProtocols));
    expect(html).toContain(`grid-template-columns:${NARROW_COLUMN}`);
    expect(html).not.toContain("grid-template-columns:1fr 1fr");
  });

  it("has no two-column template left that ignores the breakpoint", () => {
    expect(CODE.match(/gridTemplateColumns/g)).toHaveLength(1);
  });
});

describe("a row", () => {
  beforeEach(() => { viewport.narrow = false; });

  it("from 768px up keeps its label whole and its value beside it, as before", () => {
    const html = renderToStaticMarkup(createElement(WgInterface, { s: WG, heading: "wg0" }));
    const rows = rowStyles(html);
    expect(rows.length).toBeGreaterThan(0);
    for (const r of rows) {
      expect(r).toContain("gap:12px");
      expect(r).not.toContain("flex-wrap");
    }
    // One label and one value per row, so the loops below check every row
    // and cannot pass by matching nothing.
    const labels = labelStyles(html);
    expect(labels.length).toBe(rows.length);
    for (const l of labels) expect(l).toContain("flex-shrink:0");
    const values = valueStyles(html);
    expect(values.length).toBe(rows.length);
    for (const v of values) {
      expect(v).toContain("min-width:0");
      expect(v).toContain("overflow-wrap:anywhere");
      expect(v).not.toContain("margin-left");
    }
  });

  it("below 768px may put its value on the next line instead of squeezing it", () => {
    viewport.narrow = true;
    const html = renderToStaticMarkup(createElement(WgInterface, { s: WG, heading: "wg0" }));
    const rows = rowStyles(html);
    expect(rows.length).toBeGreaterThan(0);
    for (const r of rows) {
      expect(r).toContain("flex-wrap:wrap");
      // Still 12px between label and value on one line; only 2px when the
      // value moves to the line below, so it reads as that label's value.
      expect(r).toContain("gap:2px 12px");
    }
    const labels = labelStyles(html);
    expect(labels.length).toBe(rows.length);
    // A label wider than the whole row wraps between words rather than
    // running past the screen's edge.
    for (const l of labels) expect(l).toContain("flex-shrink:1");
    const values = valueStyles(html);
    expect(values.length).toBe(rows.length);
    for (const v of values) {
      expect(v).toContain("min-width:0");
      expect(v).toContain("overflow-wrap:anywhere");
      // A value alone on its line stays on the right, where it is on one line.
      expect(v).toContain("margin-left:auto");
    }
  });
});

describe("the IPsec proposal", () => {
  beforeEach(() => { viewport.narrow = false; });

  const P = "AES_GCM_16-256/PRF_HMAC_SHA2_384/ECP_256/KE1_ML_KEM_768/PPK";
  const render = (proposal: string | null | undefined) =>
    renderToStaticMarkup(createElement(IpsecProposal, { proposal }));

  it("is what the Proposal row of the IPsec lane shows", () => {
    expect(CODE).toContain('<Row k="Proposal" v={<IpsecProposal proposal={ipsec.proposal} />} />');
  });

  it("from 768px up is the plain string, as before", () => {
    expect(render(P)).toBe(P);
    expect(render(P)).not.toContain("<wbr");
  });

  it("below 768px may end a line after any '/', so a line ends between algorithms", () => {
    viewport.narrow = true;
    expect(render(P)).toBe(
      "AES_GCM_16-256/<wbr/>PRF_HMAC_SHA2_384/<wbr/>ECP_256/<wbr/>KE1_ML_KEM_768/<wbr/>PPK");
  });

  it("adds no characters: without the break opportunities it is the same string", () => {
    viewport.narrow = true;
    expect(render(P).replace(/<wbr\/>/g, "")).toBe(P);
  });

  it("reads as not negotiated, on both sides of the breakpoint, when there is none", () => {
    for (const narrow of [false, true]) {
      viewport.narrow = narrow;
      expect(render(null)).toBe("— not negotiated —");
      expect(render(undefined)).toBe("— not negotiated —");
    }
  });
});

describe("long unbroken tokens", () => {
  it("the ESP proposal line and a failed request's error text may break anywhere", () => {
    expect(CODE).toMatch(/overflowWrap: "anywhere" \}\}>\s*\{k\.name\} · \{k\.state\}/);
    expect(CODE).toMatch(/role="status" style=\{\{[^}]*overflowWrap: "anywhere"/);
  });
});

describe("the column-aligned notes under the lanes", () => {
  beforeEach(() => { viewport.narrow = false; });

  /** The notes' <pre> and whatever comes right before it, from the whole page. */
  function notes(): { before: string; pre: string; text: string; html: string } {
    const html = renderToStaticMarkup(createElement(VpnProtocols));
    const m = /(<\/h3>|<div[^>]*>)<pre style="([^"]*)">([^<]*)<\/pre>/.exec(html);
    expect(m, "the notes' <pre> is gone").not.toBeNull();
    return { before: m![1], pre: m![2], text: m![3], html };
  }

  const BOX = "overflow-x:auto;max-width:100%";
  const TEXT = "margin:0;font-size:12px;line-height:1.5;color:#cbd6f5";
  const HEADING = "Two independent mechanisms — why both are needed";

  it("from 768px up are the <pre> that scrolls inside itself, straight under the heading", () => {
    const { before, pre, html } = notes();
    expect(pre).toBe(`${TEXT};${BOX}`);
    // No wrapper: the <pre> follows the heading directly. And a server render
    // measures nothing, so the <pre> is not (yet) a region either.
    expect(before).toBe("</h3>");
    expect(html).not.toMatch(/role="region"/);
  });

  it("from 768px up the <pre> becomes the named region while it scrolls, and only then", () => {
    expect(CODE).toContain("const [wideRef, wideScrolls] = useScrollsSideways<HTMLPreElement>();");
    expect(CODE).toMatch(
      /<pre ref=\{wideRef\} \{\.\.\.scrollRegionAttributes\(wideScrolls, MECHANISMS_REGION_LABEL\)\}\s*style=\{\{ \.\.\.textStyle, overflowX: "auto", maxWidth: "100%" \}\}>/);
  });

  it("below 768px scroll in a ScrollRegion, with a little side padding on the text", () => {
    viewport.narrow = true;
    const { before, pre } = notes();
    // The server render of a ScrollRegion is its plain box.
    expect(before).toBe(`<div style="${BOX}">`);
    expect(CODE).toContain("<ScrollRegion aria-label={MECHANISMS_REGION_LABEL}>");
    // The region is the one box that scrolls, so it is the one the arrow keys
    // scroll once Tab has reached it. The padding keeps the first column of
    // text off the region's focus ring.
    const pad = Number(/const NARROW_NOTES_PAD_X_PX = (\d+);/.exec(CODE)?.[1]);
    expect(pad).toBeGreaterThan(0);
    expect(pre).toBe(`${TEXT};padding:0 ${pad}px`);
  });

  it("the region is named from the heading's one constant, with its em dash as a comma", () => {
    expect(CODE).toContain(`const MECHANISMS_HEADING = "${HEADING}";`);
    expect(CODE).toContain('const MECHANISMS_REGION_LABEL = MECHANISMS_HEADING.replace(" — ", ", ");');
    expect(CODE).toMatch(/<h3 [^>]*>\s*\{MECHANISMS_HEADING\}\s*<\/h3>/);
    expect(HEADING.replace(" — ", ", ")).toBe("Two independent mechanisms, why both are needed");
    for (const narrow of [false, true]) {
      viewport.narrow = narrow;
      expect(notes().html).toContain(`>${HEADING}</h3>`);
    }
  });

  it("say the same on both sides of the breakpoint", () => {
    const wide = notes().text;
    viewport.narrow = true;
    expect(notes().text).toBe(wide);
    expect(wide).toContain("RFC 9370 — strengthens the KEY EXCHANGE");
  });
});
