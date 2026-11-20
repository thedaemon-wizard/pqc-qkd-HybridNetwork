/**
 * /protocol-lab says it is a simulation before anything runs, and labels
 * every number by where it came from.
 *
 * The running stack relays nothing and re-routes nothing, so a page that drew
 * relay and re-routing without saying so up front would read as a view of the
 * stack. Asserted on the source: the banner must be UNCONDITIONAL, which a
 * render after Run cannot distinguish from one that appears only then.
 */
import { describe, expect, it } from "vitest";

import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const SRC = join(HERE, "..");
const ROOT = join(SRC, "..", "..", "..");
const PAGE = readFileSync(join(HERE, "ProtocolLab.tsx"), "utf8");
const APP = readFileSync(join(SRC, "App.tsx"), "utf8");
const SVG = readFileSync(join(SRC, "components", "TopologyPresetSvg.tsx"), "utf8");
/** The pages that read the running stack; none may import the simulation. */
const LIVE_STATE_PAGES = ["Topology", "Benchmarks", "VpnProtocols", "Console"];

describe("the banner", () => {
  const banner = PAGE.slice(PAGE.indexOf('<div role="note"'), PAGE.indexOf("</div>", PAGE.indexOf('<div role="note"')));

  it("is rendered unconditionally, above the controls", () => {
    expect(banner).toMatch(/<b>Simulation\.<\/b>/);
    // Nothing between the page's return and the banner can hide it.
    const before = PAGE.slice(PAGE.lastIndexOf("  return ("), PAGE.indexOf('<div role="note"'));
    expect(before).not.toMatch(/&&|\?/);
    expect(PAGE.indexOf('<div role="note"')).toBeLessThan(PAGE.indexOf("▶ Run"));
  });

  it("says what the running stack does and does not do", () => {
    const text = banner.replace(/\s+/g, " ");
    expect(text).toMatch(/nothing is observed from the running stack/);
    expect(text).toMatch(/implements no trusted-node key relay and no re-routing/);
    expect(text).toMatch(/switched off on this demo/);
    expect(text).toMatch(/No qkdnetsim binary is run/);
  });
});

describe("labels", () => {
  it("names reported and model values as such", () => {
    expect(PAGE).toMatch(/Rate \(reported\)/);
    expect(PAGE).toMatch(/Rate \(model, this project\)/);
    expect(PAGE).toMatch(/Delivered, simulated/);
  });

  it("exports the SVG it draws, and that id is unique in the repository", () => {
    expect(PAGE).toMatch(/pngTargetSelector="#protocol-lab-topology-svg"/);
    expect(SVG).toMatch(/id="protocol-lab-topology-svg"/);
    const hits = execFileSync("git", ["grep", "--untracked", "-l", 'id="protocol-lab-topology-svg"', "--", "services/webui-frontend/src", ":!*.test.ts"],
      { cwd: ROOT, encoding: "utf8" }).trim().split("\n").filter(Boolean);
    expect(hits).toEqual(["services/webui-frontend/src/components/TopologyPresetSvg.tsx"]);
  });
});

describe("registration", () => {
  it("is in the sidebar and the router", () => {
    expect(APP).toMatch(/\{ to: "\/protocol-lab", label: "Protocol Lab" \}/);
    expect(APP).toMatch(/<Route path="\/protocol-lab" element=\{<ProtocolLab \/>\} \/>/);
  });

  it("keeps simulated values off the live-state pages", () => {
    for (const f of LIVE_STATE_PAGES) {
      expect(readFileSync(join(HERE, `${f}.tsx`), "utf8"), f).not.toMatch(/protocolLab/);
    }
  });
});

describe("the subtitle", () => {
  // /e2e also runs in the browser, on stand-in keys, so sending the reader
  // there for "the running stack" contradicted that page and this one.
  it("names only live-state pages as the running stack", () => {
    const start = PAGE.indexOf("subtitle={<>");
    const subtitle = PAGE.slice(start, PAGE.indexOf("</>}", start)).replace(/\s+/g, " ");
    const named = subtitle.match(/running stack on ([^,.]*)/);
    expect(named, subtitle).not.toBeNull();
    const routes = [...named![1].matchAll(/<code>(\/[\w-]*)<\/code>/g)].map((m) => m[1]);
    const live = LIVE_STATE_PAGES.map((f) => APP.match(new RegExp(`<Route path="(/[\\w-]*)" element=\\{<${f} />\\}`))?.[1]);
    expect(live).not.toContain(undefined);
    expect(routes.length).toBeGreaterThan(0);
    for (const r of routes) expect(live, r).toContain(r);
  });
});
