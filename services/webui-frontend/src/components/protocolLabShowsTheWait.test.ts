/**
 * /protocol-lab on a slow route and on a network that counts nothing: the
 * drawing says what the run is waiting for and what it does not draw, and a
 * change of network while a tick is playing does not take the page down.
 */
import { describe, expect, it } from "vitest";

import { readFileSync } from "node:fs";
import { join } from "node:path";

import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";

import { colors } from "../lib/commonStyles";
import { PRESETS, presetById } from "../lib/sim/protocolLab/publishedNetworks";
import { routeSupply } from "../lib/sim/protocolLab/view";
import { ProtocolLabSim, type ProtocolLabState } from "../lib/sim/protocolLabSim";
import { RunSeeds } from "../lib/sim/runSeed";
import { ROUTE_ONLY_NOTE, topologyBand } from "./LiveTopology";
import TopologyPresetSvg from "./TopologyPresetSvg";

/** The state after each of `ticks` Steps of free play. */
function steps(presetId: string, ticks: number): ProtocolLabState[] {
  const out: ProtocolLabState[] = [];
  let last!: ProtocolLabState;
  let n = 0;
  const sim = new ProtocolLabSim((s) => { last = s; }, {
    seeds: new RunSeeds(3), newKsid: () => `ksid-${++n}`, presetId,
  });
  for (let i = 0; i < ticks; i++) { sim.step(); out.push(last); }
  sim.dispose();
  return out;
}

const svg = (s: ProtocolLabState, waitingOn: string | null) => renderToStaticMarkup(createElement(TopologyPresetSvg, {
  preset: presetById(s.preset_id), links: s.links, route: s.route, downNodes: s.down_nodes,
  accounting: s.accounting, waitingOn,
}));

describe("a route slower than its demand (Thuringia)", () => {
  const thu = steps("thuringia-2026", 21);
  const seventh = thu[6];
  // SND-ERF reports 12.7 bit/s and a key is 256 bits: about 20 ticks a key.
  const part = (7 * 12.7) / 256;

  it("names the hop the relay waits on, and how much of its next key it has made", () => {
    expect(seventh.last_tick?.waitingOn).toBe("SND-ERF");
    expect(seventh.links.find((l) => l.id === "SND-ERF")!.nextKeyFraction).toBeCloseTo(part, 9);
    const band = topologyBand(presetById("thuringia-2026"), seventh, null, false);
    expect(band[1]).toBe("t = 7 s; stepped; waiting for key on SND-ERF (next key 34 %)");
    expect(topologyBand(presetById("thuringia-2026"), seventh, null, true)[1])
      .toBe("t = 7 s; stepped; waiting for key on SND-ERF");
  });

  it("waits on nothing in the tick the key is relayed", () => {
    const relayed = thu.find((s) => s.last_tick?.relay)!;
    expect(relayed.tick).toBe(21);
    expect(relayed.last_tick?.waitingOn).toBeNull();
    expect(thu.slice(0, 20).every((s) => s.last_tick?.waitingOn === "SND-ERF")).toBe(true);
  });

  it("draws that hop's plate amber and its bar as the key it is making", () => {
    const html = svg(seventh, "SND-ERF");
    expect(html).toContain('data-next-key="SND-ERF"');
    expect(html).toContain(`stroke="${colors.warn}" stroke-width="1.75"`);
    const bar = /<rect x="[\d.]+" y="([\d.]+)" width="([\d.]+)" height="3" fill="[^"]+"><\/rect><rect x="[\d.]+" y="\1" width="([\d.]+)" height="3" fill="[^"]+" data-next-key="SND-ERF"/.exec(html)!;
    expect(Number(bar[3]) / Number(bar[2])).toBeCloseTo(part, 6);
    const plain = svg(seventh, null);
    expect(plain).not.toContain("data-next-key");
    expect(plain).not.toContain('stroke-width="1.75"');
  });

  it("says what the route can supply, from the rate as printed", () => {
    expect(routeSupply(presetById("thuringia-2026"), seventh)).toEqual({
      hop: "SND-ERF", reported: "average 12.7 ± 10.3 bps", supply: "one 256-bit key about every 20 s",
    });
  });
});

describe("networks whose route keeps up", () => {
  it("wait on nothing", () => {
    for (const id of ["cambridge-2019", "secoqc-vienna-2008", "tokyo-2010"]) {
      expect(steps(id, 30).every((s) => s.last_tick?.waitingOn === null), id).toBe(true);
    }
  });

  it("supply in keys per second", () => {
    const s = steps("cambridge-2019", 1)[0];
    expect(routeSupply(presetById("cambridge-2019"), s)?.supply).toMatch(/^about \d+ keys\/s$/);
  });
});

describe("a network that counts nothing (MadQCI)", () => {
  const mad = steps("madqci-2024", 3);

  it("says in the drawing that no key is drawn, and why", () => {
    const preset = presetById("madqci-2024");
    expect(topologyBand(preset, mad[2], null, false)[0]).toBe(`Simulation, not the running stack. ${ROUTE_ONLY_NOTE}`);
    expect(topologyBand(preset, mad[2], null, true)[0]).toBe("Simulation, not the running stack.");
    for (const p of PRESETS.filter((x) => x.meta.id !== "madqci-2024")) {
      const s = steps(p.meta.id, 1)[0];
      expect(topologyBand(p, s, null, false)[0], p.meta.id).not.toContain(ROUTE_ONLY_NOTE);
    }
  });

  it("makes no key and waits on nothing", () => {
    expect(mad.every((s) => s.last_tick?.waitingOn === null && s.last_tick?.relay === null)).toBe(true);
    expect(mad[2].links.every((l) => l.nextKeyFraction === null)).toBe(true);
    expect(routeSupply(presetById("madqci-2024"), mad[2])).toBeNull();
  });
});

describe("a step left over from the previous network", () => {
  it("is named while it is within this network's tick", () => {
    const s = steps("cambridge-2019", 1)[0];
    expect(topologyBand(presetById("cambridge-2019"), s, 1, false)[1]).toContain("; now 2 of 5, ETSI 004 stream");
  });

  it("past this network's tick adds nothing, rather than failing", () => {
    // Cambridge's tick has five parts and MadQCI's one: switching while part 2
    // was playing took the deployed page down (2026-11-20).
    const s = steps("madqci-2024", 1)[0];
    for (const at of [1, 2, 4]) {
      const band = topologyBand(presetById("madqci-2024"), s, at, false);
      expect(band[1]).not.toContain("now");
    }
  });
});

describe("the legend", () => {
  const SRC = readFileSync(join(new URL(".", import.meta.url).pathname, "LiveTopology.tsx"), "utf8");

  it("lists no key and no bar where the accounting draws none", () => {
    expect(SRC).toMatch(/const routeOnly = state\.accounting === "route-only";/);
    expect(SRC).toMatch(/const hasBars = state\.accounting === "keys" \|\| state\.accounting === "stores";/);
    expect(SRC).toMatch(/\{!routeOnly && <span><Dot color=\{colors\.accent\} \/> key crossing/);
    expect(SRC).toMatch(/\{!routeOnly && <span><Dot color=\{colors\.warn\} \/> key in the clear/);
    expect(SRC).toMatch(/\{!compact && hasBars && <span style=\{\{ color: colors\.qkd \}\}>bar under a caption/);
  });
});
