/**
 * The /keyflow Sankey graph, as data so it can be checked.
 *
 * It lived inline in KeyFlow.tsx as three parallel arrays, and reading them the
 * way Plotly does showed the figure was not the derivation the page describes:
 *
 *   source: [0, 1, 2, 3, 4, 5, 3, 5]
 *   target: [1, 2, 3, 6, 5, 6, 6, 6]
 *   value:  [200, 120, 100, 32, 256, 32, 32, 32]
 *
 *   * node 7, "WireGuard PSK", appeared in NEITHER source nor target, so the
 *     one edge the page's own sentence promises -- "fused by HKDF-SHA3-256 into
 *     the 32-byte WireGuard PSK" -- was the single edge never drawn. Total flow
 *     out of the HKDF node: 0.
 *   * (3,6) appeared at indices 3 AND 6, (5,6) at 5 AND 7. Both HKDF inputs
 *     were drawn twice, so 128 units entered a node that emits 64.
 *   * the units were mixed: 200/120/100 and 256 are BIT counts, while the four
 *     links into HKDF carried 32 -- the BYTE count of the same keys.
 *
 * Three parallel arrays are exactly the shape where that hides: nothing reads
 * them together until Plotly does, at which point a missing edge is just a node
 * drawn with no line attached, which looks like a layout quirk.
 *
 * So the graph is now data with named nodes, built into the parallel arrays by
 * one function, and checked by keyFlowGraph.test.ts.
 *
 * UNITS: bits, everywhere. Stated once here and rendered onto the page.
 */

export const KEY_FLOW_NODES = [
  "BB84 raw bits",
  "Sifted (basis-match)",
  "Reconciled (QBER ok)",
  "QKD key (256 b)",
  // NOT ML-KEM. The pinned Rosenpass (v0.2.3) names its own suite in the
  // domain-separation label at rosenpass/src/labeled_prf.rs:
  //   "Rosenpass v1 mceliece460896 Kyber512 ChaChaPoly1305 BLAKE2s"
  // Kyber512 is pre-standardisation Kyber, not FIPS 203 ML-KEM; liboqs ships
  // them as separate algorithms. The ML-KEM-768 on the IPsec lane is real
  // FIPS 203, but that is the IKE key exchange, not this input.
  "Rosenpass McEliece+Kyber512",
  "PQC key (256 b)",
  "HKDF-SHA3-256",
  "WireGuard PSK (256 b)",
] as const;

export type KeyFlowNode = (typeof KEY_FLOW_NODES)[number];

export interface KeyFlowEdge {
  from: KeyFlowNode;
  to: KeyFlowNode;
  /** BITS. Never bytes -- mixing the two is what this file exists to prevent. */
  bits: number;
  /**
   * True where the width is a plausible illustration rather than a measurement.
   *
   * The raw/sifted/reconciled widths were 200/120/100 with no source: 200->120
   * is a 60 % sifting ratio where BB84 basis reconciliation is 50 %, and
   * 120->100 was an unattributed reconciliation yield. They are kept as a
   * shape, because the block sizes here are not what /bb84 runs, but the page
   * now says so instead of letting a reader take them for data.
   */
  illustrative?: boolean;
}

/** 256 bits = the 32-byte key every leg of this actually carries. */
const KEY_BITS = 256;

export const KEY_FLOW_EDGES: KeyFlowEdge[] = [
  { from: "BB84 raw bits", to: "Sifted (basis-match)", bits: 2048, illustrative: true },
  { from: "Sifted (basis-match)", to: "Reconciled (QBER ok)", bits: 1024, illustrative: true },
  { from: "Reconciled (QBER ok)", to: "QKD key (256 b)", bits: KEY_BITS, illustrative: true },
  { from: "Rosenpass McEliece+Kyber512", to: "PQC key (256 b)", bits: KEY_BITS },
  // The two real inputs to the derivation, once each.
  { from: "QKD key (256 b)", to: "HKDF-SHA3-256", bits: KEY_BITS },
  { from: "PQC key (256 b)", to: "HKDF-SHA3-256", bits: KEY_BITS },
  // The edge the figure never drew. HKDF takes 512 bits of IKM and emits a
  // 256-bit key; the narrowing is the point of the diagram, not a mistake.
  { from: "HKDF-SHA3-256", to: "WireGuard PSK (256 b)", bits: KEY_BITS },
];

/** Build Plotly's three parallel arrays from the edge list, in one place. */
export function toSankeyLinks(edges: KeyFlowEdge[] = KEY_FLOW_EDGES) {
  const index = (n: KeyFlowNode) => {
    const i = KEY_FLOW_NODES.indexOf(n as never);
    if (i < 0) throw new Error(`unknown keyflow node: ${n}`);
    return i;
  };
  return {
    source: edges.map((e) => index(e.from)),
    target: edges.map((e) => index(e.to)),
    value: edges.map((e) => e.bits),
  };
}

/**
 * What the CHART prints, as opposed to what the data calls each node.
 *
 * Plotly draws a Sankey node's label to the right of the node, except for the
 * terminal column, which it draws to the LEFT -- into the same gap. With the
 * full names, "HKDF-SHA3-256" and "WireGuard PSK (256 b)" landed on top of each
 * other and rendered as the single unreadable token "HKDWireGuardiPSK (256 b)".
 *
 * Measured on the deployed page and bisected there, not guessed. What does NOT
 * fix it: a right margin (0, 40 and 150 px all overlap identically), explicit
 * `node.x`/`node.y` with arrangement "snap", or shortening either label alone
 * -- "HKDF-SHA3" with the full PSK name still collides, and so does "HKDF" with
 * it. Only shortening BOTH clears, at every margin tried.
 *
 * So the ids above stay full -- the tests key off the "(256 b)" in them to
 * check units -- and the chart prints these. Nothing is lost from the page: the
 * paragraph above the chart states "HKDF-SHA3-256" and the 512 -> 256 narrowing
 * in full.
 */
export const KEY_FLOW_LABELS: Record<KeyFlowNode, string> = {
  "BB84 raw bits": "BB84 raw bits",
  "Sifted (basis-match)": "Sifted (basis-match)",
  "Reconciled (QBER ok)": "Reconciled (QBER ok)",
  "QKD key (256 b)": "QKD key (256 b)",
  "Rosenpass McEliece+Kyber512": "Rosenpass McEliece+Kyber512",
  "PQC key (256 b)": "PQC key (256 b)",
  "HKDF-SHA3-256": "HKDF",
  "WireGuard PSK (256 b)": "WireGuard PSK",
};
