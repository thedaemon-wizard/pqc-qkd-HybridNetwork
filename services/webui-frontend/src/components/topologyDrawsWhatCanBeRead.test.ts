/**
 * /protocol-lab's drawing: later marks cover earlier ones, so the order is what
 * keeps a line from striking through a caption and a caption from sitting on a
 * node. Asserted on the rendered markup.
 */
import { describe, expect, it } from "vitest";

import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";

import { presetById } from "../lib/sim/protocolLab/publishedNetworks";
import { ProtocolLabSim, type ProtocolLabState } from "../lib/sim/protocolLabSim";
import { RunSeeds } from "../lib/sim/runSeed";
import { edgeLabel, DOWN_MARK } from "../lib/sim/protocolLab/view";
import RunStatusStrip, { serviceState, tickTone } from "./RunStatusStrip";
import TopologyPresetSvg from "./TopologyPresetSvg";

function stateFor(presetId: string, act: (sim: ProtocolLabSim) => void = () => {}): ProtocolLabState {
  let last!: ProtocolLabState;
  let n = 0;
  const sim = new ProtocolLabSim((s) => { last = s; }, {
    seeds: new RunSeeds(3), newKsid: () => `ksid-${++n}`, presetId,
  });
  act(sim);
  sim.dispose();
  return last;
}

const draw = (presetId: string, props: Record<string, unknown> = {}, act?: (sim: ProtocolLabSim) => void) => {
  const preset = presetById(presetId);
  const s = stateFor(presetId, act);
  return renderToStaticMarkup(createElement(TopologyPresetSvg, {
    preset, links: s.links, route: s.route, downNodes: s.down_nodes, accounting: s.accounting, ...props,
  }));
};

describe("the drawing's order", () => {
  it("is lines, then captions on plates, then nodes, then the key", () => {
    const html = draw("tokyo-2010");
    const lastLine = html.lastIndexOf("<line");
    const firstPlate = html.indexOf('rx="3"');
    const lastPlate = html.lastIndexOf('rx="3"');
    const firstNode = html.indexOf('rx="5"');
    const key = html.indexOf("<circle");
    expect(lastLine).toBeGreaterThan(-1);
    expect(lastLine).toBeLessThan(firstPlate);
    expect(lastPlate).toBeLessThan(firstNode);
    expect(firstNode).toBeLessThan(key);
  });

  it("captions every link, and a plate lies under every caption", () => {
    const preset = presetById("tokyo-2010");
    const html = draw("tokyo-2010");
    for (const l of preset.links) expect(html).toContain(edgeLabel(l).replace(/&/g, "&amp;"));
    expect(html.split('rx="3"').length - 1).toBe(preset.links.length);
  });

  it("marks a downed link's caption in words as well as colour", () => {
    const html = draw("cambridge-2019", {}, (sim) => sim.injectFailure({ kind: "node", id: "TREL" }));
    expect(html).toContain(DOWN_MARK.trim());
    expect(draw("cambridge-2019")).not.toContain(DOWN_MARK.trim());
  });

  it("keeps the key hidden until the page moves it", () => {
    expect(draw("tokyo-2010")).toMatch(/<g visibility="hidden"[^>]*><circle/);
  });
});

describe("the compact form for a phone", () => {
  it("leaves the captions out and says nothing it cannot fit", () => {
    const html = draw("tokyo-2010", { compact: true });
    expect(html).not.toContain('rx="3"');
    expect(html).not.toContain(" km");
  });

  it("still draws every node", () => {
    const preset = presetById("madqci-2024");
    const html = draw("madqci-2024", { compact: true });
    for (const n of preset.nodes) expect(html).toContain(`>${n.label}<`);
  });
});

describe("the status strip", () => {
  const strip = (s: ProtocolLabState, stepIndex: number | null = null) =>
    renderToStaticMarkup(createElement(RunStatusStrip, { state: s, stepIndex, routeJustChanged: false }));

  it("names the stages before anything has run, and no outcome", () => {
    const html = strip(stateFor("cambridge-2019"));
    expect(html).toContain("Generate keys");
    expect(html).toContain("Press Run or Step");
    expect(html).not.toMatch(/✓ done/);
  });

  it("says the outcome of every stage once the tick has played", () => {
    const html = strip(stateFor("cambridge-2019", (sim) => sim.step()));
    expect(html).toContain("Tick 1");
    expect(html).toMatch(/✓ done/);
    expect(html).not.toContain('aria-current="step"');
  });

  it("shows only the stages the play has reached", () => {
    const s = stateFor("cambridge-2019", (sim) => sim.step());
    const html = strip(s, 1);
    expect(html).toContain('aria-current="step"');
    expect(html.split("visibility:hidden").length - 1).toBe(s.last_tick!.steps.length - 2);
  });

  it("announces the route as a status, in words", () => {
    const html = strip(stateFor("cambridge-2019"));
    expect(html).toMatch(/role="status"[^>]*>Route: /);
  });

  it("does not call a run with no route anything but that", () => {
    const s = stateFor("cambridge-2019", (sim) => {
      sim.injectFailure({ kind: "node", id: "TREL" });
      sim.step();
    });
    expect(serviceState(s)).toEqual({ label: "no route", outcome: "fail" });
    expect(strip(s)).toContain("Route: none");
  });

  it("has not started before the first tick", () => {
    expect(serviceState(stateFor("cambridge-2019")).label).toBe("not started");
  });

  it("colours a tick by what it did", () => {
    const base = { tick: 1, sim_time_s: 1, started_at: 0, ui_dwell_ms: "" as const, nominal_dwell_ms: 300,
                   relays: 0 as const, event: "", buffers: {} };
    const tone = (route: string, delivered_bits: number, unmet_bits: number) =>
      tickTone({ ...base, route, delivered_bits, unmet_bits });
    const [ok, part, bad, none, due] = [tone("A>B", 8, 0), tone("A>B", 8, 8), tone("A>B", 0, 8), tone("", 0, 0), tone("A>B", 0, 0)];
    expect(new Set([ok, part, bad, due]).size).toBe(4);
    expect(none).toBe(bad);
  });
});
