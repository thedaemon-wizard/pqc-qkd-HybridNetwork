/**
 * ProtocolLabSim: the controls mean what they say, key material stays out of
 * exports, and the module computes everything itself.
 */
import { afterAll, beforeAll, describe, expect, it } from "vitest";

import { readFileSync, readdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import {
  HISTORY_LIMIT, NOMINAL_TICK_DWELL_MS, PREFIX_HEX, ProtocolLabSim,
  protocolLabCsvRows, type ProtocolLabState,
} from "./protocolLabSim";
import { BUNDLED_PARAMS } from "./keyrate";
import { RunSeeds } from "./runSeed";

const HERE = dirname(fileURLToPath(import.meta.url));
const SRC_ROOT = join(HERE, "..", "..");

const realWindow = (globalThis as { window?: unknown }).window;
beforeAll(() => {
  (globalThis as { window?: unknown }).window = {
    setInterval: (fn: () => void, ms: number) => setInterval(fn, ms),
    clearInterval: (id: number) => clearInterval(id),
  };
});
afterAll(() => {
  if (realWindow === undefined) delete (globalThis as { window?: unknown }).window;
  else (globalThis as { window?: unknown }).window = realWindow;
});

function driven(presetId = "cambridge-2019", seed = 11) {
  const seen: ProtocolLabState[] = [];
  let n = 0;
  const sim = new ProtocolLabSim((s) => seen.push(s), {
    seeds: new RunSeeds(seed), newKsid: () => `ksid-${++n}`, presetId,
  });
  return { sim, seen, last: () => seen[seen.length - 1] };
}

describe("run controls", () => {
  it("a step from idle emits stepped and tick 1", () => {
    const { sim, last } = driven();
    expect(last().status).toBe("idle");
    sim.step();
    expect(last().status).toBe("stepped");
    expect(last().tick).toBe(1);
  });

  it("a step from paused advances one tick and stays paused", () => {
    const { sim, last } = driven();
    sim.start(); sim.pause();
    const t = last().tick;
    sim.step();
    expect(last().status).toBe("paused");
    expect(last().tick).toBe(t + 1);
    sim.dispose();
  });

  it("a step while running is refused", () => {
    const { sim, seen } = driven();
    sim.start();
    const before = seen.length;
    sim.step();
    expect(seen.length).toBe(before);
    sim.dispose();
  });

  it("reset returns to idle at tick 0 with the history cleared", () => {
    const { sim, last } = driven();
    for (let i = 0; i < 3; i++) sim.step();
    sim.reset();
    expect(last().status).toBe("idle");
    expect(last().tick).toBe(0);
    expect(last().history).toEqual([]);
  });

  it("paces itself with its own dwell, distinct from /e2e and /paper-flow", () => {
    expect(NOMINAL_TICK_DWELL_MS).toBe(300);
  });
});

describe("relay", () => {
  it("recovers the sent key after every hop's pad, and keeps prefixes only", () => {
    const { sim, last } = driven("tokyo-2010");
    for (let i = 0; i < 3; i++) sim.step();
    const r = last().last_relay!;
    expect(r.recovered_equals_sent).toBe(true);
    expect(r.hops).toBe(2);
    expect(r.pad_prefixes).toHaveLength(2);
    expect(new Set(r.pad_prefixes).size).toBe(2);
    for (const p of [r.key_prefix, ...r.pad_prefixes]) expect(p).toHaveLength(PREFIX_HEX);
  });

  it("puts no full key in the JSON a visitor can export", () => {
    const { sim, last } = driven("tokyo-2010");
    for (let i = 0; i < 5; i++) sim.step();
    const json = JSON.stringify(last());
    const fullKeyHex = new RegExp(`[0-9a-f]{${BUNDLED_PARAMS.outBitsPerKey / 4}}`);
    expect(json).not.toMatch(fullKeyHex);
  });

  it("clears the relay sample on reset and dispose", () => {
    const { sim, last } = driven("tokyo-2010");
    for (let i = 0; i < 3; i++) sim.step();
    expect(last().last_relay).not.toBeNull();
    sim.reset();
    expect(last().last_relay).toBeNull();
    sim.dispose();
  });

  it("debits every hop of the route equally", () => {
    const { sim, last } = driven("tokyo-2010");
    sim.setDemand("K1", "O2", 0);
    sim.step();
    const s = last();
    const relayed = s.stream!.undelivered;
    expect(relayed).toBeGreaterThan(0);
    const generated = (id: string) => {
      const l = s.links.find((x) => x.id === id)!;
      return Math.min(BUNDLED_PARAMS.poolLowWatermark, Math.floor(l.genBps! / BUNDLED_PARAMS.outBitsPerKey));
    };
    for (const id of s.route!.linkIds) {
      expect(s.links.find((l) => l.id === id)!.storedKeys, id).toBe(generated(id) - relayed);
    }
    // A link off the route kept everything it generated.
    const off = s.links.find((l) => l.id === "K1-O1")!;
    expect(s.route!.linkIds).not.toContain("K1-O1");
    expect(off.storedKeys).toBe(generated("K1-O1"));
  });

  it("keeps a link with no reported rate at zero and says why", () => {
    const { sim, last } = driven("tokyo-2010");
    for (let i = 0; i < 3; i++) sim.step();
    const hongo = last().links.find((l) => l.id === "O2-HONGO")!;
    expect(hongo.genBps).toBeNull();
    expect(hongo.storedKeys).toBe(0);
    expect(hongo.genNote).toMatch(/no single reported rate/);
  });
});

describe("failures", () => {
  it("re-routes on a link failure and records the reason", () => {
    const { sim, last } = driven("cambridge-2019");
    sim.step();
    sim.injectFailure({ kind: "link", id: "CAPE-TREL", reason: "outage" });
    expect(last().route!.nodes).toEqual(["TREL", "ENGI", "CAPE"]);
    expect(last().reroutes.at(-1)!.reason).toBe("link-down");
  });

  it("takes every incident link down with a node", () => {
    const { sim, last } = driven("cambridge-2019");
    sim.injectFailure({ kind: "node", id: "ENGI" });
    expect(last().links.filter((l) => l.down).map((l) => l.id).sort()).toEqual(["ENGI-CAPE", "TREL-ENGI"]);
  });

  it("with an endpoint down, GET_KEY reports no QKD connection (status 4)", () => {
    const { sim, last } = driven("cambridge-2019");
    sim.step();
    sim.injectFailure({ kind: "node", id: "CAPE" });
    sim.step();
    expect(last().route).toBeNull();
    expect(last().stream!.last_status).toBe(4);
  });

  it("replays the same random failures for the same seed", () => {
    const pick = (seed: number) => {
      const { sim } = driven("secoqc-vienna-2008", seed);
      return [0, 1, 2].map(() => {
        const f = sim.injectRandomFailure();
        return f && f.kind === "link" ? f.id : null;
      });
    };
    const a = pick(42);
    expect(a.every((x) => x !== null)).toBe(true);
    expect(pick(42)).toEqual(a);
  });
});

describe("exports", () => {
  it("ships the CSV columns the other simulators ship, and no duration_ms", () => {
    const { sim, last } = driven();
    for (let i = 0; i < 3; i++) sim.step();
    const rows = protocolLabCsvRows(last());
    expect(rows).toHaveLength(3);
    for (const k of ["tick", "sim_time_s", "started_at", "ui_dwell_ms", "nominal_dwell_ms",
                     "preset", "scenario", "demand", "route", "relays", "delivered_bits",
                     "unmet_bits", "event"]) expect(Object.keys(rows[0])).toContain(k);
    expect(Object.keys(rows[0])).not.toContain("duration_ms");
    expect(rows[0].nominal_dwell_ms).toBe(NOMINAL_TICK_DWELL_MS);
    expect(Object.keys(rows[0]).some((k) => k.startsWith("buf_"))).toBe(true);
  });

  it("names the engine and bounds the history", () => {
    const { sim, last } = driven();
    for (let i = 0; i < HISTORY_LIMIT + 5; i++) sim.step();
    expect(last().engine).toBe("client-side (JS)");
    expect(last().history.length).toBe(HISTORY_LIMIT);
  });
});

// ---- source scans -----------------------------------------------------------
const labFiles = (): string[] => [
  join(HERE, "protocolLabSim.ts"),
  ...readdirSync(join(HERE, "protocolLab"))
    .filter((f) => f.endsWith(".ts") && !f.endsWith(".test.ts"))
    .map((f) => join(HERE, "protocolLab", f)),
  join(SRC_ROOT, "pages", "ProtocolLab.tsx"),
  ...["TopologyPresetSvg", "QBufferGauge", "SBufferQueue", "SDNControlPanel",
      "LoadPresetDropdown", "MessageTimeline"].map((c) => join(SRC_ROOT, "components", `${c}.tsx`)),
];

describe("source", () => {
  it("makes no network request from any Protocol Lab file", () => {
    for (const f of labFiles()) {
      const src = readFileSync(f, "utf8");
      expect(src, f).not.toMatch(/\bfetch\(|WebSocket|XMLHttpRequest|navigator\.sendBeacon/);
      // etsi014Shapes.ts names this stack's 014 path prefix as a SHAPE for the
      // timeline, which is the one place an /api/ string belongs here.
      if (!f.endsWith("etsi014Shapes.ts")) expect(src, f).not.toMatch(/["'`]\/api\//);
    }
  });

  it("carries no pool or key-size literal outside the data module", () => {
    // 256, 64 and 8 are config values (out_bits_per_key, pool_max_size,
    // pool_low_watermark); they reach this code through BUNDLED_PARAMS.
    for (const f of labFiles().filter((x) => !x.endsWith("publishedNetworks.ts"))) {
      // Named constants are declarations, not uses: MAX_SIMPLE_PATHS = 64 is
      // an enumeration bound, unrelated to pool_max_size.
      const code = readFileSync(f, "utf8")
        .replace(/\/\*[\s\S]*?\*\//g, "").replace(/\/\/[^\n]*/g, "")
        .replace(/^export const [A-Z_]+ = [\d_.e]+;$/gm, "");
      expect(code, f).not.toMatch(/(?<![\w.])(256|64)(?![\w.])/);
      expect(code, f).not.toMatch(/(?<![\w.])1e9(?![\w.])/);
    }
  });

  it("calls the key-rate model from one place only", () => {
    const callers = [...labFiles(), ...readdirSync(join(SRC_ROOT, "pages")).map((f) => join(SRC_ROOT, "pages", f))]
      .filter((f) => /\.tsx?$/.test(f) && !f.endsWith(".test.ts") && !f.endsWith(".test.tsx"))
      .filter((f) => readFileSync(f, "utf8").includes("skrBpsForLink("));
    expect(callers.map((f) => f.split("/").pop())).toEqual(["rates.ts"]);
  });
});
