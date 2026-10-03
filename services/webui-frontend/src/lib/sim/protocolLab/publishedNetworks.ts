/**
 * Published QKD network topologies for /protocol-lab, restated as facts.
 *
 * Every number here was re-read from the source paper and is stored the way
 * the source PRINTS it -- `printed: "2.40"`, not `2.4` -- with the unit, any
 * qualifier ("about", "average", ">"), a reference and a provenance. Numeric
 * values are derived from the printed text by `quantityValue`, so there is one
 * copy of each number and the page can show it with the source's precision.
 *
 * What is NOT here, deliberately:
 *   - figures, maps or text from the papers. Two of the five sources are
 *     non-commercial licences (SECOQC: CC BY-NC-SA 3.0; Tokyo: Optica's
 *     open-access agreement), so this module keeps numbers and names only and
 *     draws its own layout. Coordinates are this project's schematic, not
 *     traced from any figure, and there is no latitude or longitude;
 *   - rates the source does not give. A missing value is `null`, never a guess.
 *     A link with no reported rate generates nothing in the simulation, and
 *     the page says so;
 *   - a "Czech National 13-node" topology. No source for one was found: the
 *     only Czech paper models a six-node chain with calculated, not measured,
 *     rates. See docs/roadmap.md.
 *
 * Imports nothing, so the data can be checked in isolation.
 */

export type Provenance = "text" | "table" | "figure-label" | "inferred";

export interface Cited {
  ref: string;
  provenance: Provenance;
}

export type Unit =
  | "km" | "m" | "dB"
  | "bit/s" | "bps" | "kbit/s" | "kbps" | "Mbit/s" | "Mbps"
  | "%" | "MiB" | "keys" | "keys/s" | "s" | "min" | "days";

/** A value as a source printed it. */
export interface Quantity extends Cited {
  printed: string;
  unit: Unit;
  qualifier?: string | null;
  sd?: string | null;
}

export type Protocol =
  | "decoy-bb84" | "sarg04" | "bb84-or-sarg04" | "cow" | "dps"
  | "bbm92" | "entanglement" | "cv-qkd" | "multiple-systems" | "none";

/** The only protocol this repository's key-rate model describes. */
export const MODEL_ELIGIBLE: readonly Protocol[] = ["decoy-bb84"];

export interface PresetNode {
  id: string;
  label: string;
  x: number;
  y: number;
  alias?: string[];
}

export interface PresetLink {
  id: string;
  a: string;
  b: string;
  /**
   * `non-qkd-keystore`: a hop fed from previously generated keys in a local
   * store rather than a live QKD link. The source does not say how those keys
   * were generated, so this does not claim they were not QKD output. Never
   * routed.
   */
  kind: "qkd" | "non-qkd-keystore";
  /** The system as the source names it. */
  system: string | null;
  protocol: Protocol;
  protocolRef: Cited | null;
  medium: "fibre" | "free-space" | null;
  endpoints: Cited;
  length: Quantity | null;
  lengthAlt: Quantity[];
  loss: Quantity | null;
  /** Secret-key rate as published. */
  rate: Quantity | null;
  qber: Quantity | null;
  aerial?: Quantity;
  buried?: Quantity;
  campaign?: Quantity;
  notes: string[];
}

export interface PresetMeta {
  id: string;
  title: string;
  citation: string;
  doi: string | null;
  arxiv: string | null;
  url: string;
  licence: string;
  reuse: "facts-only";
  reuseNote: string;
}

export interface TopologyPreset {
  meta: PresetMeta;
  viewBox: [number, number];
  nodes: PresetNode[];
  links: PresetLink[];
  notes: string[];
  /**
   * How free play accounts for key on this preset.
   *   keys       -- each link generates at its reported rate into a buffer that
   *                 follows this repository's KeyPool rules;
   *   route-only -- rates are not available per link, so routes are chosen by
   *                 which links are up and nothing is counted.
   */
  freePlay: { accounting: "keys" | "route-only"; why: string };
  /** The endpoints free play starts with. */
  defaultDemand: { from: string; to: string };
}

export type FailureTarget =
  | { kind: "link"; id: string; reason?: "outage" | "qber-alarm" }
  | { kind: "node"; id: string };

// ---------------------------------------------------------------------------
// Units
// ---------------------------------------------------------------------------

/** SECOQC's own definition, NJP 11 075001 section 5.1: 1 MiB = 1 048 576 bytes. */
export const MIB_BITS = 1_048_576 * 8;

const TO_BASE: Record<Unit, number> = {
  km: 1, m: 1e-3, dB: 1,
  "bit/s": 1, bps: 1, "kbit/s": 1e3, kbps: 1e3, "Mbit/s": 1e6, Mbps: 1e6,
  "%": 0.01, MiB: MIB_BITS, keys: 1, "keys/s": 1, s: 1, min: 60, days: 86_400,
};

/**
 * The numeric value in the base unit of its dimension: km, dB, bit/s,
 * fraction, bits, keys, seconds.
 */
export function quantityValue(q: Quantity): number {
  const n = Number(q.printed);
  if (!Number.isFinite(n)) throw new Error(`not a single number: "${q.printed}" (${q.ref})`);
  return n * TO_BASE[q.unit];
}

/**
 * Half a unit in the last digit the source printed, in the same base unit as
 * `quantityValue`: "6.1" % gives 0.0005, because the source's 6.1 stands for
 * anything from 6.05 to 6.15. A comparison closer than this is not settled by
 * the printed number. Only plain decimals are accepted; anything else throws
 * rather than guessing a precision the source did not print.
 */
export function quantityHalfStep(q: Quantity): number {
  const m = /^-?\d+(?:\.(\d+))?$/.exec(q.printed);
  if (!m) throw new Error(`not a plain decimal: "${q.printed}" (${q.ref})`);
  const decimals = m[1]?.length ?? 0;
  return 0.5 * Math.pow(10, -decimals) * TO_BASE[q.unit];
}

const q = (printed: string, unit: Unit, ref: string, provenance: Provenance,
           extra: { qualifier?: string; sd?: string } = {}): Quantity =>
  ({ printed, unit, ref, provenance, qualifier: extra.qualifier ?? null, sd: extra.sd ?? null });

// ---------------------------------------------------------------------------
// 1. Cambridge quantum network, 2019 (default)
// ---------------------------------------------------------------------------
const CAM = "Dynes et al., npj Quantum Inf. 5, 101 (2019)";

const cambridge: TopologyPreset = {
  meta: {
    id: "cambridge-2019",
    title: "Cambridge quantum network (2019)",
    citation: `${CAM}`,
    doi: "10.1038/s41534-019-0221-4",
    arxiv: null,
    url: "https://doi.org/10.1038/s41534-019-0221-4",
    licence: "CC BY 4.0",
    reuse: "facts-only",
    reuseNote: "Link lengths, losses and 580-day average rates restated with attribution; no figure reproduced.",
  },
  viewBox: [520, 300],
  nodes: [
    { id: "CAPE", label: "CAPE", x: 100, y: 150 },
    { id: "TREL", label: "TREL", x: 420, y: 70 },
    { id: "ENGI", label: "ENGI", x: 390, y: 235 },
  ],
  links: [
    {
      id: "CAPE-TREL", a: "CAPE", b: "TREL", kind: "qkd", system: "Toshiba",
      protocol: "decoy-bb84", protocolRef: { ref: `${CAM}, Methods`, provenance: "text" },
      medium: "fibre", endpoints: { ref: `${CAM}, Results`, provenance: "text" },
      length: q("10.6", "km", `${CAM}, Results`, "text"), lengthAlt: [],
      loss: q("3.9", "dB", `${CAM}, Results`, "text"),
      rate: q("2.58", "Mbps", `${CAM}, Results`, "text", { qualifier: "average" }),
      qber: null,
      notes: ["580-day average including outages.", "QBER is only plotted in the source, so it is not restated."],
    },
    {
      id: "TREL-ENGI", a: "TREL", b: "ENGI", kind: "qkd", system: "Toshiba",
      protocol: "decoy-bb84", protocolRef: { ref: `${CAM}, Methods`, provenance: "text" },
      medium: "fibre", endpoints: { ref: `${CAM}, Results`, provenance: "text" },
      length: q("9.8", "km", `${CAM}, Results`, "text"), lengthAlt: [],
      loss: q("4.2", "dB", `${CAM}, Results`, "text"),
      rate: q("2.40", "Mbps", `${CAM}, Results`, "text", { qualifier: "average" }),
      qber: null,
      notes: ["580-day average including outages."],
    },
    {
      id: "ENGI-CAPE", a: "ENGI", b: "CAPE", kind: "qkd", system: "Toshiba",
      protocol: "decoy-bb84", protocolRef: { ref: `${CAM}, Methods`, provenance: "text" },
      medium: "fibre", endpoints: { ref: `${CAM}, Results`, provenance: "text" },
      length: q("5.0", "km", `${CAM}, Results`, "text"), lengthAlt: [],
      loss: q("2.5", "dB", `${CAM}, Results`, "text", { qualifier: "~" }),
      rate: q("2.22", "Mbps", `${CAM}, Results`, "text", { qualifier: "average" }),
      qber: null,
      notes: ["580-day average including outages."],
    },
  ],
  notes: [
    "Each node is a trusted node holding a store of global keys, shared with its peers over one-time-pad tunnels encrypted by QKD keys.",
  ],
  freePlay: { accounting: "keys", why: "All three links have a reported average rate." },
  defaultDemand: { from: "TREL", to: "CAPE" },
};

// ---------------------------------------------------------------------------
// 2. SECOQC Vienna, 2008
// ---------------------------------------------------------------------------
const SEC = "Peev et al., New J. Phys. 11, 075001 (2009)";

const secoqc: TopologyPreset = {
  meta: {
    id: "secoqc-vienna-2008",
    title: "SECOQC Vienna (2008)",
    citation: SEC,
    doi: "10.1088/1367-2630/11/7/075001",
    arxiv: null,
    url: "https://doi.org/10.1088/1367-2630/11/7/075001",
    licence: "CC BY-NC-SA 3.0",
    reuse: "facts-only",
    reuseNote: "Non-commercial licence: only re-typed numbers and names are used, on this project's own layout. No figure, map or text is reproduced.",
  },
  viewBox: [640, 320],
  nodes: [
    { id: "STP", label: "STP", x: 70, y: 250 },
    { id: "BRT", label: "BRT", x: 230, y: 250 },
    { id: "GUD", label: "GUD", x: 440, y: 250 },
    { id: "SIE", label: "SIE", x: 230, y: 80 },
    { id: "ERD", label: "ERD", x: 440, y: 80 },
    { id: "FOR", label: "FOR", x: 580, y: 80, alias: ["FRM"] },
  ],
  links: [
    {
      id: "STP-BRT", a: "STP", b: "BRT", kind: "qkd", system: "COW",
      protocol: "cow", protocolRef: { ref: `${SEC}, Fig. 2`, provenance: "figure-label" },
      medium: "fibre", endpoints: { ref: `${SEC}, Fig. 2`, provenance: "figure-label" },
      length: q("85", "km", `${SEC}, Fig. 2`, "figure-label"),
      lengthAlt: [
        q("83", "km", `${SEC}, abstract ("the longest link being 83 km")`, "text"),
        q("82", "km", `${SEC}, Fig. 11 caption`, "text"),
      ],
      loss: null, rate: null, qber: null,
      notes: ["The source gives this link's rates as a plot only (Fig. 11)."],
    },
    {
      id: "SIE-BRT", a: "SIE", b: "BRT", kind: "qkd", system: "Toshiba",
      protocol: "decoy-bb84", protocolRef: { ref: `${SEC}, section 3.2 (WCP decoy state + vacuum BB84)`, provenance: "text" },
      medium: "fibre", endpoints: { ref: `${SEC}, section 3.2 (Breitenfurterstrasse to Siemensstrasse)`, provenance: "text" },
      length: q("32", "km", `${SEC}, Fig. 2`, "figure-label"),
      lengthAlt: [q("33", "km", `${SEC}, section 3.2`, "text")],
      loss: q("7.5", "dB", `${SEC}, section 3.2 ("measured to be 7.5 dB")`, "text"),
      rate: q("3.1", "kbit/s", `${SEC}, section 3.2`, "text", { qualifier: "24 h average" }),
      qber: q("2.6", "%", `${SEC}, section 3.2`, "text", { qualifier: "average" }),
      notes: [],
    },
    {
      id: "SIE-ERD", a: "SIE", b: "ERD", kind: "qkd", system: "Entangled photons",
      protocol: "entanglement", protocolRef: { ref: `${SEC}, section 3.4`, provenance: "text" },
      medium: "fibre", endpoints: { ref: `${SEC}, section 3.4 ("between the nodes ERD and SIE")`, provenance: "text" },
      length: q("16", "km", `${SEC}, section 3.4`, "text"), lengthAlt: [],
      loss: null,
      rate: q("2.5", "kbit/s", `${SEC}, section 3.4`, "text"),
      qber: q("3.5", "%", `${SEC}, section 3.4`, "text"),
      notes: ["The source also reports a reliable rate above 2 kbit/s over the whole demonstration."],
    },
    {
      id: "ERD-FOR", a: "ERD", b: "FOR", kind: "qkd", system: "Free-space",
      protocol: "decoy-bb84", protocolRef: { ref: `${SEC}, section 3.6 (decoy states, 850 nm)`, provenance: "text" },
      medium: "free-space", endpoints: { ref: `${SEC}, Fig. 2 (ERD to FRM); section 5.1.2 names it FOR`, provenance: "inferred" },
      length: q("80", "m", `${SEC}, section 3.6`, "text"), lengthAlt: [],
      loss: null,
      rate: q("17", "kbit/s", `${SEC}, section 3.6`, "text", { qualifier: "up to" }),
      qber: q("2.3", "%", `${SEC}, section 3.6`, "text"),
      notes: [
        "FOR (section 5.1.2) is read as the node Fig. 2 labels FRM; the text places FRM in a separate building near ERD.",
        "A free-space link with no stated loss, so this repository's fibre model is not applied.",
      ],
    },
    {
      id: "ERD-GUD", a: "ERD", b: "GUD", kind: "qkd", system: "CV",
      protocol: "cv-qkd", protocolRef: { ref: `${SEC}, section 3.5`, provenance: "text" },
      medium: "fibre", endpoints: { ref: `${SEC}, Fig. 2`, provenance: "figure-label" },
      length: q("6", "km", `${SEC}, Fig. 2`, "figure-label"),
      lengthAlt: [q("6.2", "km", `${SEC}, section 3.5`, "text")],
      loss: q("2.8", "dB", `${SEC}, section 3.5`, "text", { qualifier: "approx." }),
      rate: q("8", "kbit/s", `${SEC}, section 3.5`, "text", { qualifier: "average" }),
      qber: null,
      notes: ["57 h of continuous operation."],
    },
    {
      id: "ERD-BRT", a: "ERD", b: "BRT", kind: "qkd", system: "id Quantique (idQ-1)",
      protocol: "sarg04", protocolRef: { ref: `${SEC}, section 3.1 ("The SARG protocol has been used for the link BREIT-ERD")`, provenance: "text" },
      medium: "fibre", endpoints: { ref: `${SEC}, section 3.1`, provenance: "text" },
      length: q("25", "km", `${SEC}, Fig. 2`, "figure-label"), lengthAlt: [],
      loss: q("5.75", "dB", `${SEC}, section 3.1`, "text"),
      rate: q("1", "kbit/s", `${SEC}, section 3.1`, "text", { qualifier: "almost equal to the SECOQC criterion of" }),
      qber: null,
      notes: ["The source states this mean rate only relative to the 1 kbit/s SECOQC criterion."],
    },
    {
      id: "SIE-GUD", a: "SIE", b: "GUD", kind: "qkd", system: "id Quantique (idQ-2)",
      protocol: "bb84-or-sarg04", protocolRef: { ref: `${SEC}, section 3.1`, provenance: "text" },
      medium: "fibre", endpoints: { ref: `${SEC}, Fig. 2`, provenance: "inferred" },
      length: q("22", "km", `${SEC}, Fig. 2`, "figure-label"), lengthAlt: [],
      loss: null, rate: null, qber: null,
      notes: [
        "Endpoints read from the diagonal in Fig. 2; section 5.1.2's five FOR-to-BRT routes come out as five only with this link.",
        "The source says id Quantique followed BB84 and SARG instructions but names SARG only for ERD-BRT.",
      ],
    },
    {
      id: "BRT-GUD", a: "BRT", b: "GUD", kind: "qkd", system: "id Quantique (idQ-3)",
      protocol: "bb84-or-sarg04", protocolRef: { ref: `${SEC}, section 3.1`, provenance: "text" },
      medium: "fibre", endpoints: { ref: `${SEC}, Fig. 2`, provenance: "figure-label" },
      length: q("19", "km", `${SEC}, Fig. 2`, "figure-label"), lengthAlt: [],
      loss: null, rate: null, qber: null,
      notes: [],
    },
  ],
  notes: [
    "The six-node prototype ran in October 2008. Each link is a different vendor's system; the network layer relays key hop by hop through trusted nodes.",
  ],
  freePlay: { accounting: "keys", why: "Five of eight links have a reported rate; the rest generate nothing in the simulation and say so." },
  defaultDemand: { from: "FOR", to: "BRT" },
};

// ---------------------------------------------------------------------------
// 3. Tokyo QKD Network, 2010
// ---------------------------------------------------------------------------
const TOK = "Sasaki et al., Opt. Express 19, 10387 (2011)";

const tokyo: TopologyPreset = {
  meta: {
    id: "tokyo-2010",
    title: "Tokyo QKD Network (2010)",
    citation: TOK,
    doi: "10.1364/OE.19.010387",
    arxiv: "1103.3566",
    url: "https://doi.org/10.1364/OE.19.010387",
    licence: "Optica open-access agreement (non-commercial)",
    reuse: "facts-only",
    reuseNote: "Only re-typed numbers and names are used, on this project's own layout. No figure or text is reproduced.",
  },
  viewBox: [640, 320],
  nodes: [
    { id: "K3", label: "Koganei-3", x: 70, y: 250 },
    { id: "K2", label: "Koganei-2", x: 230, y: 250 },
    { id: "O2", label: "Otemachi-2", x: 410, y: 250 },
    { id: "HONGO", label: "Hongo", x: 570, y: 250 },
    { id: "K1", label: "Koganei-1", x: 230, y: 80 },
    { id: "O1", label: "Otemachi-1", x: 410, y: 80 },
  ],
  links: [
    {
      id: "K1-O1", a: "K1", b: "O1", kind: "qkd", system: "NEC-NICT",
      protocol: "decoy-bb84", protocolRef: { ref: `${TOK}, section 2`, provenance: "text" },
      medium: "fibre", endpoints: { ref: `${TOK}, Fig. 1(b)`, provenance: "figure-label" },
      length: q("45", "km", `${TOK}, section 3.1`, "text"), lengthAlt: [],
      loss: q("14.5", "dB", `${TOK}, section 3.1`, "text"),
      rate: q("81.7", "kbps", `${TOK}, section 3.1`, "text", { qualifier: "average, asymptotic estimate," }),
      qber: q("2.7", "%", `${TOK}, section 3.1`, "text", { qualifier: "average" }),
      notes: ["NEC's decoy analysis used an asymptotic estimate."],
    },
    {
      id: "K1-K2", a: "K1", b: "K2", kind: "qkd", system: "NTT-NICT",
      protocol: "dps", protocolRef: { ref: `${TOK}, section 2`, provenance: "text" },
      medium: "fibre", endpoints: { ref: `${TOK}, Fig. 1(b)`, provenance: "figure-label" },
      length: q("90", "km", `${TOK}, section 3.3`, "text"), lengthAlt: [],
      loss: q("27", "dB", `${TOK}, section 3.3`, "text"),
      rate: q("2.1", "kbps", `${TOK}, section 3.3`, "text", { qualifier: "about" }),
      qber: q("2.3", "%", `${TOK}, section 3.3`, "text", { qualifier: "about" }),
      notes: ["A loop-back link: both ends are at Koganei and the fibre runs via Otemachi."],
    },
    {
      id: "O1-O2", a: "O1", b: "O2", kind: "qkd", system: "Mitsubishi",
      protocol: "decoy-bb84", protocolRef: { ref: `${TOK}, section 2`, provenance: "text" },
      medium: "fibre", endpoints: { ref: `${TOK}, Fig. 1(b)`, provenance: "figure-label" },
      length: q("24", "km", `${TOK}, section 3.4`, "text"), lengthAlt: [],
      loss: q("13", "dB", `${TOK}, section 3.4`, "text"),
      rate: q("2", "kbps", `${TOK}, section 3.4`, "text"),
      qber: q("4.5", "%", `${TOK}, section 3.4`, "text", { qualifier: "about" }),
      notes: ["A loop-back link between Otemachi and Hakusan."],
    },
    {
      id: "K3-K2", a: "K3", b: "K2", kind: "qkd", system: "All Vienna",
      protocol: "bbm92", protocolRef: { ref: `${TOK}, section 2`, provenance: "text" },
      medium: "fibre", endpoints: { ref: `${TOK}, Fig. 1(b)`, provenance: "figure-label" },
      length: q("1", "km", `${TOK}, Fig. 1(b)`, "figure-label"), lengthAlt: [],
      loss: q("1", "dB", `${TOK}, Fig. 1(b)`, "figure-label"),
      rate: null, qber: null,
      notes: [
        "The only rate the source reports for this system (around 0.25 kbps, section 3.6) was measured with artificially added loss over extra fibre loops and a lab spool, not on this link, so it is not used.",
      ],
    },
    {
      id: "K2-O2", a: "K2", b: "O2", kind: "qkd", system: "TREL",
      protocol: "decoy-bb84", protocolRef: { ref: `${TOK}, section 2`, provenance: "text" },
      medium: "fibre", endpoints: { ref: `${TOK}, Fig. 1(b)`, provenance: "figure-label" },
      length: q("45", "km", `${TOK}, section 3.2`, "text"), lengthAlt: [],
      loss: q("14.5", "dB", `${TOK}, section 3.2`, "text"),
      rate: q("304", "kbps", `${TOK}, section 3.2`, "text", { qualifier: "24 h average" }),
      qber: null,
      notes: [],
    },
    {
      id: "O2-HONGO", a: "O2", b: "HONGO", kind: "qkd", system: "IDQ",
      protocol: "sarg04", protocolRef: { ref: `${TOK}, section 2`, provenance: "text" },
      medium: "fibre", endpoints: { ref: `${TOK}, section 2 (the Otemachi-Hongo link)`, provenance: "text" },
      length: q("13", "km", `${TOK}, section 3.5`, "text"), lengthAlt: [],
      loss: q("11", "dB", `${TOK}, Fig. 1(b)`, "figure-label"),
      rate: null,
      qber: q("2", "%", `${TOK}, section 3.5`, "text", { qualifier: "approximately" }),
      notes: ["The source gives a range, 400-420 bps after an added filter (300-350 bps before), so no single rate is used."],
    },
  ],
  notes: [
    "Six QKD systems from nine organisations formed a six-node mesh over the JGN2plus testbed in October 2010.",
  ],
  freePlay: { accounting: "keys", why: "Four of six links have a single reported rate; the other two generate nothing in the simulation and say so." },
  defaultDemand: { from: "K1", to: "O2" },
};

// ---------------------------------------------------------------------------
// 4. MadQCI, Madrid, 2024
// ---------------------------------------------------------------------------
const MAD = "Martin et al., npj Quantum Inf. 10, 80 (2024)";

function madLink(id: string, a: string, b: string, km: string, db: string,
                 fig2: string, fig3: string, extra: Partial<PresetLink> = {}): PresetLink {
  return {
    id, a, b, kind: "qkd", system: null, protocol: "multiple-systems",
    protocolRef: { ref: `${MAD}, Table 1`, provenance: "table" },
    medium: "fibre", endpoints: { ref: `${MAD}, Fig. 3 (${fig3})`, provenance: "figure-label" },
    length: q(km, "km", `${MAD}, Fig. 2 (${fig2})`, "figure-label"), lengthAlt: [],
    loss: q(db, "dB", `${MAD}, Fig. 2 (${fig2})`, "figure-label"),
    rate: null, qber: null,
    notes: [],
    ...extra,
  };
}

const madqci: TopologyPreset = {
  meta: {
    id: "madqci-2024",
    title: "MadQCI, Madrid (2024)",
    citation: MAD,
    doi: "10.1038/s41534-024-00873-2",
    arxiv: "2311.12791",
    url: "https://doi.org/10.1038/s41534-024-00873-2",
    licence: "CC BY 4.0",
    reuse: "facts-only",
    reuseNote: "Span lengths and losses restated with attribution; no figure reproduced.",
  },
  viewBox: [700, 320],
  nodes: [
    { id: "QUIRON", label: "Quirón", x: 60, y: 140 },
    { id: "QUIJOTE", label: "Quijote", x: 190, y: 140 },
    { id: "QUINTIN", label: "Quintín", x: 190, y: 270 },
    { id: "QUEVEDO", label: "Quevedo", x: 340, y: 140 },
    { id: "QUIJANO", label: "Quijano", x: 340, y: 270 },
    { id: "QUINTO", label: "Quinto", x: 490, y: 270 },
    { id: "NORTE", label: "Norte", x: 490, y: 140 },
    { id: "CONCEPCION", label: "Concepción", x: 630, y: 70 },
    { id: "DISTRITO", label: "Distrito", x: 630, y: 210 },
  ],
  links: [
    madLink("QUIRON-QUIJOTE", "QUIRON", "QUIJOTE", "24.5", "8.72", "span 1", "L1"),
    madLink("QUIJOTE-QUINTIN", "QUIJOTE", "QUINTIN", "24.1", "7.47", "span 2", "L2"),
    madLink("QUIJOTE-QUEVEDO", "QUIJOTE", "QUEVEDO", "7.8", "1.40", "span 3", "L3", {
      lengthAlt: [q("7.4", "km", `${MAD}, Fig. 3 (L3)`, "figure-label")],
    }),
    madLink("QUEVEDO-NORTE", "QUEVEDO", "NORTE", "3.9", "3", "span 4", "L4"),
    madLink("NORTE-CONCEPCION", "NORTE", "CONCEPCION", "8.1", "2.9", "span 5", "L7", {
      notes: ["Fig. 2 numbers this span 5 and Fig. 3 numbers it L7; the two figures swap 5 and 7, so Table 1 rows 5 and 7 cannot be bound to a span."],
    }),
    madLink("NORTE-DISTRITO", "NORTE", "DISTRITO", "15", "8.3", "span 6", "L6", {
      lengthAlt: [q("15.0", "km", `${MAD}, Fig. 3 (L6)`, "figure-label")],
    }),
    madLink("CONCEPCION-DISTRITO", "CONCEPCION", "DISTRITO", "15.3", "14.3", "span 7", "L5", {
      notes: ["Fig. 2 numbers this span 7 and Fig. 3 numbers it L5 (see Norte-Concepción)."],
    }),
    madLink("QUEVEDO-QUIJANO", "QUEVEDO", "QUIJANO", "33.1", "11.8", "span 8", "L8"),
    madLink("QUIJANO-QUINTO", "QUIJANO", "QUINTO", "1.9", "2.0", "span 9", "L9"),
  ],
  notes: [
    "Several vendors' discrete- and continuous-variable systems share spans through optical switches; Table 1 lists each system's average rate, some per direction and from different periods.",
    "Table 1's optical-bypass 'combination' rows are omitted.",
    "MadQCI's encryptors took keys over ETSI GS QKD 004 and 014 (Martin et al., section on applications).",
  ],
  freePlay: {
    accounting: "route-only",
    why: "Table 1's rates belong to individual systems, some per direction and from different periods, so this release binds no rate to a span. Routes are chosen by which spans are up; nothing is counted.",
  },
  defaultDemand: { from: "QUIRON", to: "DISTRITO" },
};

// ---------------------------------------------------------------------------
// 5. Thuringia medical-data chain (arXiv:2608.18869v2)
// ---------------------------------------------------------------------------
const THU = "Dosan et al., arXiv:2608.18869v2 (2026)";

const thuringia: TopologyPreset = {
  meta: {
    id: "thuringia-2026",
    title: "Thuringia medical-data chain (2026)",
    citation: THU,
    doi: null,
    arxiv: "2608.18869",
    url: "https://arxiv.org/abs/2608.18869v2",
    licence: "CC BY 4.0",
    reuse: "facts-only",
    reuseNote: "Table I values and link descriptions restated with attribution; no figure reproduced.",
  },
  viewBox: [640, 260],
  nodes: [
    { id: "SND", label: "SND", x: 70, y: 130 },
    { id: "ERF", label: "ERF", x: 240, y: 130 },
    { id: "IOF", label: "IOF", x: 410, y: 130 },
    { id: "UKJ", label: "UKJ", x: 570, y: 130 },
  ],
  links: [
    {
      id: "SND-ERF", a: "SND", b: "ERF", kind: "qkd", system: "Entangled photons (BBM92)",
      protocol: "bbm92", protocolRef: { ref: `${THU}, section I ("following the BBM92 protocol")`, provenance: "text" },
      medium: "fibre", endpoints: { ref: `${THU}, Table I`, provenance: "table" },
      length: q("70", "km", `${THU}, Table I`, "table"), lengthAlt: [],
      loss: q("17", "dB", `${THU}, Table I (section IV.B: "approximately 17 dB")`, "table", { qualifier: ">" }),
      // "average": the source's word for both (section IV.A: the QBERs are
      // "averages over the respective measurement campaigns", and this link's
      // rate is "the reported average SKR").
      rate: q("12.7", "bps", `${THU}, Table I`, "table", { qualifier: "average", sd: "10.3" }),
      qber: q("13.3", "%", `${THU}, Table I`, "table", { qualifier: "average", sd: "9.6" }),
      aerial: q("51", "km", `${THU}, section IV.B`, "text"),
      buried: q("19", "km", `${THU}, Fig. 1(a)`, "figure-label"),
      campaign: q("22", "days", `${THU}, section IV.A`, "text"),
      notes: [
        "Mostly aerial fibre; QBER variation tracks wind speed (section IV.B).",
        "Its rate is the average of per-interval rates: intervals whose QBER exceeded the security threshold produced no key, although the campaign-mean QBER is itself above that threshold (section IV.A). Free play here generates at this mean continuously.",
      ],
    },
    {
      id: "ERF-IOF", a: "ERF", b: "IOF", kind: "qkd", system: "Entangled photons (BBM92)",
      protocol: "bbm92", protocolRef: { ref: `${THU}, section I ("following the BBM92 protocol")`, provenance: "text" },
      medium: "fibre", endpoints: { ref: `${THU}, Table I ("Jena - Erfurt")`, provenance: "table" },
      length: q("69", "km", `${THU}, Table I`, "table"),
      lengthAlt: [q("75", "km", `${THU}, section IV.A (the 2022 route, "approximately 75-km")`, "text", { qualifier: "approximately" })],
      loss: q("21", "dB", `${THU}, Table I (section IV.B: "approximately 21 dB")`, "table", { qualifier: ">" }),
      // The QBER is an average in so many words (section IV.A). The rate is
      // not called one explicitly, so it keeps no qualifier.
      rate: q("22.2", "bps", `${THU}, Table I`, "table", { sd: "4.7" }),
      qber: q("6.1", "%", `${THU}, Table I`, "table", { qualifier: "average", sd: "0.8" }),
      aerial: q("4", "km", `${THU}, section IV.B`, "text"),
      buried: q("65", "km", `${THU}, section IV.B`, "text", { qualifier: "approximately" }),
      campaign: q("2", "days", `${THU}, section IV.A`, "text"),
      notes: ["Mostly buried fibre."],
    },
    {
      id: "IOF-UKJ", a: "IOF", b: "UKJ", kind: "non-qkd-keystore", system: null,
      protocol: "none", protocolRef: null,
      medium: null, endpoints: { ref: `${THU}, section III`, provenance: "text" },
      length: null, lengthAlt: [], loss: null, rate: null, qber: null,
      notes: ["'previously generated keys from a local keystore were used instead, owing to hardware-availability constraints' (section III); Fig. 1(c) labels both ends 'QKD Device (Pre-Shared Keys)'. The paper does not say how the stored keys were generated. Never routed here."],
    },
  ],
  notes: [
    "The two QKD rates come from separate campaigns, two and 22 days long; the links were not run at the same time (section IV.A).",
    "Table I's ± values are temporal standard deviations over each campaign, not measurement uncertainties (section IV.A).",
    "The paper runs arnika with QKD keys only on each hop and carries post-quantum protection in a separate end-to-end tunnel (QuantShake, SND to UKJ) that the trusted nodes forward without holding its key (sections III and V). This repository's two-node WireGuard lane follows that layering (a wg0 hop tunnel, with Rosenpass keying a wg1 data tunnel inside it), but arnika mixes a PQC-HPKE key agreed hop by hop into each hop's WireGuard PSK, where the paper uses QKD keys alone (also per leg in docker-compose.multihop.yml, where the relay node holds both legs' keys). An end-to-end layer across a relay exists here only in the /paper-flow simulation. Relaying key across this chain exists only in the simulation.",
  ],
  freePlay: { accounting: "keys", why: "Both QKD links have a reported rate; the keystore hop is never routed." },
  defaultDemand: { from: "SND", to: "IOF" },
};

export const PRESETS: readonly TopologyPreset[] = [cambridge, secoqc, tokyo, madqci, thuringia];

export const DEFAULT_PRESET_ID = "cambridge-2019";

export function presetById(id: string): TopologyPreset {
  const p = PRESETS.find((x) => x.meta.id === id);
  if (!p) throw new Error(`unknown preset: ${id}`);
  return p;
}

// ---------------------------------------------------------------------------
// Cited scenarios
// ---------------------------------------------------------------------------

export interface ScenarioEvent {
  id: string;
  label: string;
  action: "fail" | "restore";
  target: FailureTarget;
  ref: string;
}

interface ScenarioBase {
  id: string;
  presetId: string;
  title: string;
  summary: string;
  tick: { seconds: number; why: string };
  demand: { from: string; to: string; rate: Quantity };
  preferredRoute?: { nodes: string[]; ref: string };
  /** Links the source shows were not part of the run. */
  notInRun?: { linkIds: string[]; ref: string; provenance: Provenance };
  events: ScenarioEvent[];
  /** What the source reports, for comparison with the replay. */
  published: { routes: string[][]; ref: string; note: string };
  limits: string[];
}

/** Stores and generation per link, in the source's units. */
export interface StoresScenario extends ScenarioBase {
  accounting: "stores";
  threshold: Quantity;
  stores: Record<string, Quantity>;
  /**
   * `equals-demand` until `untilS`; `none` -- the source says it did not
   * generate; `unquantified` -- the source says it generated but gives no
   * rate, replayed as zero, which makes the replayed route lifetime a lower
   * bound.
   */
  generation: Record<string, { kind: "equals-demand"; until: Quantity } | { kind: "none" } | { kind: "unquantified" }>;
}

/** A service-side key store refilled by relay (Cambridge). */
export interface ServiceBufferScenario extends ScenarioBase {
  accounting: "service-buffer";
  serviceBuffer: { capacity: Quantity; refillAt: Quantity; refillTo: Quantity; readingNote: string };
}

/** Route choice only; the source states no store sizes. */
export interface RouteOnlyScenario extends ScenarioBase {
  accounting: "route-only";
}

export type Scenario = StoresScenario | ServiceBufferScenario | RouteOnlyScenario;

const secoqcReroute: StoresScenario = {
  id: "secoqc-reroute-2008",
  presetId: "secoqc-vienna-2008",
  title: "SECOQC re-routing under key exhaustion",
  summary: "An application draws about 1 KiB/s between FOR and BRT while most devices are off; routes fail over as link stores reach their minimum.",
  accounting: "stores",
  tick: { seconds: 60, why: "One minute, the resolution the prototype reported at (section 5.1.1). A resolution choice, not physics." },
  demand: { from: "FOR", to: "BRT", rate: q("8192", "bit/s", `${SEC}, Fig. 22 caption ("approximately 1 KiB s-1 = 8192 bit s-1")`, "text", { qualifier: "approximately" }) },
  threshold: q("2", "MiB", `${SEC}, section 5.1.2`, "text"),
  stores: {
    "ERD-FOR": q("12", "MiB", `${SEC}, section 5.1.2`, "text", { qualifier: "approximately" }),
    "ERD-BRT": q("5.5", "MiB", `${SEC}, section 5.1.2`, "text", { qualifier: "approximately" }),
    "SIE-ERD": q("6.6", "MiB", `${SEC}, section 5.1.2`, "text", { qualifier: "approximately" }),
    "SIE-BRT": q("6", "MiB", `${SEC}, section 5.1.2`, "text", { qualifier: "approximately" }),
    "ERD-GUD": q("3.8", "MiB", `${SEC}, section 5.1.2`, "text", { qualifier: "approximately" }),
    "BRT-GUD": q("4.9", "MiB", `${SEC}, section 5.1.2`, "text", { qualifier: "approximately" }),
  },
  generation: {
    "ERD-FOR": { kind: "equals-demand", until: q("45", "min", `${SEC}, section 5.1.2`, "text") },
    "SIE-ERD": { kind: "unquantified" },
    "SIE-BRT": { kind: "unquantified" },
    "ERD-BRT": { kind: "unquantified" },
    "ERD-GUD": { kind: "none" },
    "BRT-GUD": { kind: "none" },
  },
  notInRun: {
    linkIds: ["SIE-GUD", "STP-BRT"],
    ref: `${SEC}, section 5.1.2 ("three of these are effectively operative"); no store is plotted for STP-BRT in Fig. 22`,
    provenance: "inferred",
  },
  events: [],
  published: {
    routes: [["FOR", "ERD", "BRT"], ["FOR", "ERD", "SIE", "BRT"], ["FOR", "ERD", "GUD", "BRT"]],
    ref: `${SEC}, section 5.1.2 and Fig. 22`,
    note: "Route 1 for about an hour, route 2 until minute 144, route 3 until minute 175, then no route.",
  },
  limits: [
    "ERD-SIE, SIE-BRT and ERD-BRT generated key during the run, but the source gives no rate, so the replay generates none there: its route lifetimes are lower bounds. Route 2 lasts about 68 minutes in the replay against about 84 in the source for that reason.",
    "The source's two brief recoveries of route 1 (fresh key reaching ERD-BRT) and GUD-BRT's single key at minute 159 are not replayed.",
    "The routing rule -- fewest hops first, then the widest bottleneck -- is this project's inference: the source does not state its metric, and pure widest-bottleneck routing would pick route 2 first.",
  ],
};

const tokyoReroute: RouteOnlyScenario = {
  id: "tokyo-reroute-2010",
  presetId: "tokyo-2010",
  title: "Tokyo secure TV conference: attack and switch-over",
  summary: "A 128 kbps OTP video link from Koganei-1 to Otemachi-2 uses the route via Koganei-2; an attack on the 90 km link moves it to the route via Otemachi-1.",
  accounting: "route-only",
  tick: { seconds: 1, why: "One second; route choice only, so the resolution affects nothing but the timeline." },
  demand: { from: "K1", to: "O2", rate: q("128", "kbps", `${TOK}, section 4`, "text") },
  preferredRoute: { nodes: ["K1", "K2", "O2"], ref: `${TOK}, section 4 ("The former one was used as the primary route")` },
  events: [
    { id: "attack-k1-k2", label: "Attack the 90 km link (QBER alarm)", action: "fail",
      target: { kind: "link", id: "K1-K2", reason: "qber-alarm" }, ref: `${TOK}, section 4` },
    { id: "clear-k1-k2", label: "Clear the alarm", action: "restore",
      target: { kind: "link", id: "K1-K2" }, ref: "not in the source; lets the replay be run again" },
  ],
  published: {
    routes: [["K1", "K2", "O2"], ["K1", "O1", "O2"]],
    ref: `${TOK}, section 4`,
    note: "The KMS detected the attack within seconds, stopped the link and switched to the secondary route before stored key ran out.",
  },
  limits: [
    "The source does not state how much key the nodes held, and the 128 kbps demand is far above either route's reported rate (about 2.1 and 2 kbps), which the source reconciles with stored key. So this replay checks only which links are up: rate sufficiency is not evaluated.",
  ],
};

const cambridgeReroute: ServiceBufferScenario = {
  id: "cambridge-otp-reroute-2019",
  presetId: "cambridge-2019",
  title: "Cambridge global-key refill and link outage",
  summary: "A 100G encryptor pair between TREL and CAPE consumes global keys; the key store is refilled over one-time-pad tunnels, and a CAPE-TREL outage moves the refills round the ring.",
  accounting: "service-buffer",
  tick: { seconds: 10, why: "Ten seconds, a resolution choice: the consumer takes one key about every 2 s, so a tick is about five keys." },
  demand: {
    from: "TREL", to: "CAPE",
    rate: q("0.5", "keys/s", `${CAM}, Results (two line-card pairs, each requesting a key about every 4 s: "on average every 2 s")`, "inferred"),
  },
  serviceBuffer: {
    capacity: q("1000", "keys", `${CAM}, Fig. 3 caption`, "text"),
    refillAt: q("800", "keys", `${CAM}, Fig. 3 caption ("depleted to a level of 800 keys")`, "text"),
    refillTo: q("1000", "keys", `${CAM}, Fig. 3 caption`, "text"),
    readingNote: "The caption says the store is refilled when depleted TO 800 keys; the main text says when the keys consumed reach a threshold of 800. The caption's reading is used; under the other the store would refill at 200.",
  },
  events: [
    { id: "outage-cape-trel", label: "CAPE-TREL outage", action: "fail",
      target: { kind: "link", id: "CAPE-TREL", reason: "outage" }, ref: `${CAM}, Results and Fig. 3(b) section (ii)` },
    { id: "restore-cape-trel", label: "Restore CAPE-TREL", action: "restore",
      target: { kind: "link", id: "CAPE-TREL" }, ref: `${CAM}, Results and Fig. 3(b) section (iii)` },
  ],
  published: {
    routes: [["TREL", "CAPE"], ["TREL", "ENGI", "CAPE"], ["TREL", "CAPE"]],
    ref: `${CAM}, Results and Fig. 3(b)`,
    note: "Refills run over CAPE-TREL; during the outage they run via ENGI; on restore they return to CAPE-TREL. Key requests kept succeeding throughout.",
  },
  limits: [
    "Link stores are not stated, so a link is usable while it is up and its reported average rate covers the refill within one tick.",
    "The size of a global key in bits is not stated as such; where bits are shown, the key size is this project's config (protocol.out_bits_per_key), labelled as such.",
  ],
};

export const SCENARIOS: readonly Scenario[] = [cambridgeReroute, secoqcReroute, tokyoReroute];

export function scenariosFor(presetId: string): Scenario[] {
  return SCENARIOS.filter((s) => s.presetId === presetId);
}

export function scenarioById(id: string): Scenario {
  const s = SCENARIOS.find((x) => x.id === id);
  if (!s) throw new Error(`unknown scenario: ${id}`);
  return s;
}
