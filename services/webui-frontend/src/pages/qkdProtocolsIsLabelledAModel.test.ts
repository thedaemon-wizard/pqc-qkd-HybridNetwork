/**
 * /qkd-protocols says what it is before anything runs, makes no request of its
 * own, and keeps to what its sources allow it to say.
 *
 * The wording rules come from reading the sources in full (docs/keyrate.md
 * section 9): MDI-QKD removes attacks on the measurement unit only, its rate does
 * not beat the repeaterless bound, and a distance means little without its fibre,
 * its key-length regime and its date.
 */
import { describe, expect, it, vi } from "vitest";

import { readFileSync } from "node:fs";
import { join } from "node:path";

import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";

// Plotly reads the window as it loads, and a server render has no use for a chart.
vi.mock("react-plotly.js", () => ({ default: () => null }));

import QkdProtocols from "./QkdProtocols";
import QkdRoundSvg from "../components/QkdRoundSvg";

const HERE = new URL(".", import.meta.url).pathname;
const read = (rel: string) => readFileSync(join(HERE, rel), "utf8");
const PAGE = read("QkdProtocols.tsx");
const SVG = read("../components/QkdRoundSvg.tsx");
const ROUNDS = read("../lib/sim/qkdRounds.ts");
const RATES = read("../lib/sim/protocolRates.ts");
const APP = read("../App.tsx");

describe("the banner", () => {
  const start = PAGE.indexOf('<div role="note"');
  const banner = PAGE.slice(start, PAGE.indexOf("</div>", start)).replace(/\s+/g, " ");

  it("is rendered unconditionally, above the controls", () => {
    expect(banner).toMatch(/<b>Model, not measurement\.<\/b>/);
    const before = PAGE.slice(PAGE.lastIndexOf("  return ("), start);
    expect(before).not.toMatch(/&&|\?/);
    expect(start).toBeLessThan(PAGE.indexOf("▶ Run"));
  });

  it("says what the page is not", () => {
    expect(banner).toMatch(/idealised, with no loss, noise or eavesdropper/);
    expect(banner).toMatch(/not measured, not a finite-key bound, and not a prediction for any product/);
    expect(banner).toMatch(/no MDI-QKD or BBM92 backend, and no key from these models reaches it/);
  });
});

describe("what an export carries", () => {
  it("says inside the SVG that the round is idealised", () => {
    expect(SVG).toMatch(/Idealised round: no loss, no noise, no eavesdropper\. Not a rate or a security test\./);
    const html = renderToStaticMarkup(createElement(QkdRoundSvg, {
      protocol: "mdi", round: null, partIndex: null, photonRefs: [{ current: null }, { current: null }], compact: false,
    }));
    expect(html.indexOf("Idealised round")).toBeLessThan(html.indexOf("</svg>"));
  });

  it("exports the SVG it draws, and that id is unique", () => {
    expect(PAGE).toMatch(/pngTargetSelector="#qkd-round-svg"/);
    expect(SVG).toMatch(/id="qkd-round-svg"/);
    expect(PAGE).not.toMatch(/id="qkd-round-svg"/);
  });
});

describe("what it does not do", () => {
  it("makes no request", () => {
    for (const src of [PAGE, SVG, ROUNDS, RATES]) {
      expect(src).not.toMatch(/\bfetch\(|WebSocket|XMLHttpRequest|navigator\.sendBeacon|["'`]\/api\//);
    }
  });

  it("keeps no count of bits, which would read as a key", () => {
    expect(PAGE).toMatch(/const ROUNDS_SHOWN = \d+;/);
    expect(PAGE).not.toMatch(/\b(totalBits|keyLength|siftedCount|keyBits)\b/);
  });

  it("has no eavesdropper control", () => {
    expect(PAGE).not.toMatch(/<(Button|input|select)[^>]*\b(Eve|attack)\b/i);
    expect(PAGE).not.toMatch(/setEve|eveOn|attackOn/);
  });

  it("starts no frame loop with reduced motion asked for", () => {
    expect(PAGE).toMatch(/if \(reduced\) \{ finish\(\); return/);
    const guard = PAGE.indexOf("if (reduced) { finish();");
    expect(guard).toBeLessThan(PAGE.indexOf("requestAnimationFrame(step)"));
  });

  it("freezes on Pause", () => {
    expect(PAGE).toMatch(/function pause\(\) \{ setRunning\(false\); stopPlay\(\); \}/);
    expect(PAGE).toMatch(/const stopPlay = \(\) => \{\s*cancelAnimationFrame\(frame\.current\);/);
  });
});

describe("the wording", () => {
  const text = PAGE.replace(/\/\*[\s\S]*?\*\//g, "");

  it("does not call MDI-QKD immune or side-channel-free", () => {
    expect(text).not.toMatch(/\bimmune\b|side-channel-free|unconditional/i);
    expect(text).toMatch(/This targets attacks on the detectors only: the sources must still be trusted/);
  });

  it("does not say first, record, compliant or certified, anywhere a reader can see", () => {
    const shown = renderToStaticMarkup(createElement(QkdProtocols)).replace(/<[^>]+>/g, " ");
    expect(shown).toContain("The families compared");
    expect(shown).not.toMatch(/\b(the first|record|compliant|certified)\b/i);
  });

  it("says MDI's rate does not beat the bound, and twin-field is not point-to-point", () => {
    expect(text).toMatch(/It does not beat the repeaterless bound/);
    expect(text).toMatch(/It is not point-to-point/);
  });

  it("labels every long-distance result with its fibre and its key-length regime", () => {
    for (const [what, how] of [["1002 km", "asymptotic"], ["404 km", "finite key"], ["253.9 km", "deployed"], ["508.16 km", "spools"], ["11 km", "spools"]]) {
      const line = text.split("\n").find((l) => l.includes(what));
      expect(line, what).toBeDefined();
      expect(line!, what).toContain(how);
    }
  });

  it("does not present the 2610.11428 result as new, or at all", () => {
    expect(text).not.toContain("2610.11428");
  });

  it("names its sources", () => {
    for (const s of ["PRL 108, 130503", "PRA 86, 062319", "PRA 76, 012307", "PRL 94, 230504", "Nat. Commun. 8, 15043"]) {
      expect(text).toContain(s);
    }
  });
});

describe("registration", () => {
  it("is in the sidebar and the router", () => {
    expect(APP).toMatch(/\{ to: "\/qkd-protocols", label: "QKD Protocols" \}/);
    expect(APP).toMatch(/<Route path="\/qkd-protocols" element=\{<QkdProtocols \/>\} \/>/);
  });
});

describe("on a phone and on a desk", () => {
  it("renders on the server with its panels and no sideways template wider than a phone", () => {
    const html = renderToStaticMarkup(createElement(QkdProtocols));
    for (const h of ["One round at a time", "Key rate against fibre length", "The families compared"]) {
      expect(html).toContain(h);
    }
    for (const m of PAGE.matchAll(/minmax\((\d+)px/g)) expect(Number(m[1])).toBeLessThanOrEqual(288);
  });

  it("asks lib/layout.ts about width and motion, with no query of its own", () => {
    expect(PAGE).toMatch(/useNarrowLayout, usePrefersReducedMotion/);
    expect(PAGE).not.toMatch(/matchMedia|max-width|min-width|innerWidth/);
  });
});
