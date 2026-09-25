/**
 * The published-network data: every number cited, every licence respected,
 * nothing invented.
 */
import { describe, expect, it } from "vitest";

import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import {
  DEFAULT_PRESET_ID, MODEL_ELIGIBLE, PRESETS, SCENARIOS, presetById, quantityValue,
  type PresetLink, type Quantity,
} from "./publishedNetworks";
import { modelRateFor } from "./rates";
import { boxesFit } from "./view";
import { MAX_SIMPLE_PATHS, simplePaths } from "./routing";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = join(HERE, "..", "..", "..", "..", "..", "..");
const SRC = readFileSync(join(HERE, "publishedNetworks.ts"), "utf8");

const quantities = (l: PresetLink): Quantity[] =>
  [l.length, ...l.lengthAlt, l.loss, l.rate, l.qber, l.aerial, l.buried, l.campaign]
    .filter((x): x is Quantity => !!x);

describe("presets", () => {
  it("ships the five verified networks, Cambridge first and default", () => {
    expect(PRESETS.map((p) => p.meta.id)).toEqual([
      "cambridge-2019", "secoqc-vienna-2008", "tokyo-2010", "madqci-2024", "thuringia-2026",
    ]);
    expect(DEFAULT_PRESET_ID).toBe("cambridge-2019");
  });

  it("names a citation, a licence and a DOI or arXiv id for each", () => {
    for (const p of PRESETS) {
      expect(p.meta.citation).toBeTruthy();
      expect(p.meta.licence).toBeTruthy();
      expect(p.meta.doi ?? p.meta.arxiv).toBeTruthy();
      expect(p.meta.reuseNote).toBeTruthy();
    }
  });

  it("keeps non-commercial sources to facts only", () => {
    for (const p of PRESETS.filter((x) => /NC|non-commercial/i.test(x.meta.licence))) {
      expect(p.meta.reuse).toBe("facts-only");
      expect(p.meta.reuseNote).toMatch(/no figure/i);
    }
  });

  it("gives every number a reference and a provenance, and parses it", () => {
    for (const p of PRESETS) for (const l of p.links) for (const v of quantities(l)) {
      expect(v.ref, `${l.id}`).toBeTruthy();
      expect(["text", "table", "figure-label", "inferred"]).toContain(v.provenance);
      expect(Number.isFinite(quantityValue(v)), `${l.id} ${v.printed}`).toBe(true);
    }
  });

  it("stores printed digits, so 2.40 and 1.40 stay as printed", () => {
    const cam = presetById("cambridge-2019").links.find((l) => l.id === "TREL-ENGI")!;
    expect(cam.rate!.printed).toBe("2.40");
    const mad = presetById("madqci-2024").links.find((l) => l.id === "QUIJOTE-QUEVEDO")!;
    expect(mad.loss!.printed).toBe("1.40");
  });

  it("keeps QBER a fraction below one half and rates positive", () => {
    for (const p of PRESETS) for (const l of p.links) {
      if (l.qber) expect(quantityValue(l.qber)).toBeGreaterThanOrEqual(0);
      if (l.qber) expect(quantityValue(l.qber)).toBeLessThan(0.5);
      if (l.rate) expect(quantityValue(l.rate)).toBeGreaterThan(0);
    }
  });

  it("has unique ids, known endpoints and layouts inside the viewBox", () => {
    for (const p of PRESETS) {
      const ids = p.nodes.map((n) => n.id);
      expect(new Set(ids).size).toBe(ids.length);
      expect(new Set(p.links.map((l) => l.id)).size).toBe(p.links.length);
      for (const l of p.links) { expect(ids).toContain(l.a); expect(ids).toContain(l.b); }
      expect(boxesFit(p), p.meta.id).toBe(true);
      for (const n of p.nodes) {
        expect(Object.keys(n)).not.toContain("lat");
        expect(Object.keys(n)).not.toContain("lon");
      }
    }
  });

  it("does not exceed the path-enumeration bound on any preset", () => {
    for (const p of PRESETS) {
      const g = { nodes: p.nodes.map((n) => n.id), links: p.links };
      for (const a of g.nodes) for (const b of g.nodes) {
        if (a !== b) expect(simplePaths(g, a, b).length).toBeLessThan(MAX_SIMPLE_PATHS);
      }
    }
  });
});

describe("the values the review flagged", () => {
  it("shows SECOQC's longest link as 85 km with 83 and 82 as alternatives", () => {
    const l = presetById("secoqc-vienna-2008").links.find((x) => x.id === "STP-BRT")!;
    expect(l.length!.printed).toBe("85");
    expect(l.lengthAlt.map((x) => x.printed)).toEqual(["83", "82"]);
  });

  it("puts no rate on the Tokyo All Vienna link: its 0.25 kbps was a lab measurement", () => {
    const l = presetById("tokyo-2010").links.find((x) => x.id === "K3-K2")!;
    expect(l.rate).toBeNull();
    expect(l.notes.join(" ")).toMatch(/artificially added loss/);
  });

  it("states ERD-BRT's rate only relative to the SECOQC criterion", () => {
    const l = presetById("secoqc-vienna-2008").links.find((x) => x.id === "ERD-BRT")!;
    expect(l.rate!.qualifier).toMatch(/criterion/);
  });

  it("marks Thuringia's IOF-UKJ hop as a keystore, with nothing measured", () => {
    const l = presetById("thuringia-2026").links.find((x) => x.id === "IOF-UKJ")!;
    expect(l.kind).toBe("non-qkd-keystore");
    expect([l.length, l.loss, l.rate, l.qber]).toEqual([null, null, null, null]);
    expect(l.notes.join(" ")).toMatch(/keystore/);
  });

  it("does not call Thuringia's keystore hop 'not QKD': the source says only 'not live'", () => {
    const l = presetById("thuringia-2026").links.find((x) => x.id === "IOF-UKJ")!;
    const text = l.notes.join(" ");
    expect(text).not.toMatch(/\bnot QKD\b/);
    expect(text).toMatch(/previously generated keys from a local keystore/);
    expect(text).toMatch(/does not say how the stored keys were generated/);
  });

  it("does not claim the Thuringia layering is this repository's", () => {
    // In the paper arnika carries QKD-only keys per hop and PQC is a separate
    // end-to-end tunnel; here arnika mixes the Rosenpass key into each hop.
    const text = presetById("thuringia-2026").notes.join(" ");
    expect(text).not.toMatch(/same layering as this repository/);
    expect(text).toMatch(/QKD keys only on each hop/);
    expect(text).toMatch(/mixes a Rosenpass key into each hop's WireGuard PSK/);
  });

  it("says Thuringia's values are campaign averages with temporal spreads", () => {
    const p = presetById("thuringia-2026");
    const snd = p.links.find((x) => x.id === "SND-ERF")!;
    const erf = p.links.find((x) => x.id === "ERF-IOF")!;
    expect(snd.rate!.qualifier).toBe("average");
    expect(snd.qber!.qualifier).toBe("average");
    expect(erf.qber!.qualifier).toBe("average");
    expect(p.notes.join(" ")).toMatch(/temporal standard deviations/);
    expect(snd.notes.join(" ")).toMatch(/generates at this mean continuously/);
  });

  it("binds no MadQCI rate to a span, and says why", () => {
    const p = presetById("madqci-2024");
    expect(p.links.every((l) => l.rate === null)).toBe(true);
    expect(p.freePlay.accounting).toBe("route-only");
    expect(p.links.find((l) => l.id === "NORTE-CONCEPCION")!.notes.join(" ")).toMatch(/swap 5 and 7/);
  });

  it("keeps qualifiers the source printed", () => {
    const tok = presetById("tokyo-2010").links;
    expect(tok.find((l) => l.id === "K1-K2")!.rate!.qualifier).toBe("about");
    expect(tok.find((l) => l.id === "O1-O2")!.qber!.qualifier).toBe("about");
    const thu = presetById("thuringia-2026").links;
    expect(thu.find((l) => l.id === "SND-ERF")!.loss!.qualifier).toBe(">");
    expect(presetById("secoqc-vienna-2008").links.find((l) => l.id === "ERD-GUD")!.loss!.qualifier).toBe("approx.");
  });
});

describe("the model column", () => {
  it("is non-null exactly for decoy-BB84 fibre links with a reported loss", () => {
    for (const p of PRESETS) for (const l of p.links) {
      const eligible = l.kind === "qkd" && MODEL_ELIGIBLE.includes(l.protocol)
        && l.medium === "fibre" && l.loss !== null;
      expect(modelRateFor(l).bps !== null, `${p.meta.id} ${l.id}`).toBe(eligible);
    }
  });

  it("keeps the loss qualifier in its label", () => {
    const l = presetById("cambridge-2019").links.find((x) => x.id === "ENGI-CAPE")!;
    const m = modelRateFor(l);
    expect(m.bps).not.toBeNull();
    if (m.bps !== null) expect(m.lossShown).toBe("~2.5 dB");
  });

  it("never needs an alternative length: every link with one has a loss or is not modelled", () => {
    for (const p of PRESETS) for (const l of p.links) {
      if (l.lengthAlt.length) {
        expect(l.loss !== null || !MODEL_ELIGIBLE.includes(l.protocol), `${l.id}`).toBe(true);
      }
    }
  });
});

describe("scenarios", () => {
  it("each belongs to a preset and cites its demand", () => {
    for (const s of SCENARIOS) {
      expect(PRESETS.map((p) => p.meta.id)).toContain(s.presetId);
      expect(s.demand.rate.ref).toBeTruthy();
      expect(s.limits.length).toBeGreaterThan(0);
      expect(s.tick.why).toMatch(/resolution/i);
    }
  });
});

describe("the data module", () => {
  it("imports nothing and never refers to the qkdnetsim submodule", () => {
    expect(SRC).not.toMatch(/^import /m);
    expect(SRC).not.toMatch(/submodules\/qkdnetsim/);
  });

  it("is attributed in THIRD_PARTY_NOTICES and references", () => {
    const notices = readFileSync(join(ROOT, "docs", "THIRD_PARTY_NOTICES.md"), "utf8");
    const refs = readFileSync(join(ROOT, "docs", "references.md"), "utf8");
    for (const p of PRESETS) {
      const id = p.meta.doi ?? p.meta.arxiv!;
      expect(notices, `${p.meta.id} missing from THIRD_PARTY_NOTICES`).toContain(id);
      expect(refs, `${p.meta.id} missing from references`).toContain(id);
    }
  });

  it("agrees with docs/references.md on the Thuringia field values", () => {
    const refs = readFileSync(join(ROOT, "docs", "references.md"), "utf8");
    for (const l of presetById("thuringia-2026").links.filter((x) => x.kind === "qkd")) {
      expect(refs).toContain(`${l.rate!.printed} \\pm ${l.rate!.sd}`);
      expect(refs).toContain(`${l.qber!.printed} \\pm ${l.qber!.sd}`);
      expect(refs).toContain(`${l.length!.printed} km`);
      expect(refs).toContain(`> ${l.loss!.printed} dB`);
    }
  });
});
