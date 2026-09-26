import Plot from "react-plotly.js";
import { Link } from "react-router-dom";
import ExportToolbar from "../components/ExportToolbar";
import { PLOT_CONFIG } from "../lib/plotConfig";
import { KEY_FLOW_COLORS, KEY_FLOW_EDGES, KEY_FLOW_LABELS, KEY_FLOW_NODES, toSankeyLinks } from "./keyFlowGraph";

/**
 * Hybrid key derivation flow.
 *
 * The graph is defined in keyFlowGraph.ts as a named edge list and checked by
 * keyFlowGraph.test.ts. It used to be three parallel arrays inline here, and in
 * that form the "WireGuard PSK" node was referenced by no edge at all -- the one
 * arrow the paragraph below promises was the only one the figure did not draw.
 * See that file for the full reading.
 *
 * Since release 0.2.0 the figure has two components: the derivation into wg0's
 * PSK, and Rosenpass into wg1's. They never meet, because Rosenpass no longer
 * feeds the HKDF.
 */
export default function KeyFlow() {
  const links = toSankeyLinks();
  // By node, not by position: see KEY_FLOW_COLORS.
  const nodeColor = KEY_FLOW_NODES.map((n) => KEY_FLOW_COLORS[n]);
  // Colour each link by its SOURCE, so the lane a flow belongs to is derived
  // rather than maintained as a fourth parallel array that can fall out of step.
  const linkColor = links.source.map((i) => `${nodeColor[i]}70`);

  const data: any = [{
    type: "sankey",
    orientation: "h",
    node: {
      pad: 24,
      thickness: 22,
      // Display labels, not ids -- see KEY_FLOW_LABELS for the measured
      // reason the two rightmost differ from their ids.
      label: KEY_FLOW_NODES.map((n) => KEY_FLOW_LABELS[n]),
      color: nodeColor,
    },
    link: { ...links, color: linkColor },
  }];

  return (
    <div>
      <h2 style={{ marginTop: 0 }}>Hybrid Key Derivation Flow</h2>
      <p style={{ color: "#9aa9d8", maxWidth: 720 }}>
        The QKD key (green) and the PQC-HPKE key (purple) are fused by
        HKDF-SHA3-256 (orange) into the 256-bit WireGuard PSK of <code>wg0</code>,
        the hop tunnel. <b>Widths are bits</b> — the two 256-bit inputs give 512
        bits of keying material, and HKDF emits 256; that narrowing at the
        orange node is the derivation, not a drawing error.
      </p>
      <p style={{ color: "#9aa9d8", maxWidth: 720 }}>
        The PQC-HPKE key is one arnika agrees with its peer over its existing
        UDP socket: HPKE Base mode (RFC 9180) with the KEM MLKEM1024-P384, a
        hybrid of ML-KEM-1024 and P-384 (from draft-ietf-hpke-pq, not yet an
        RFC), the KDF HKDF-SHA384 and an export-only AEAD; the HKDF receives its
        32-byte export. Rosenpass (pink) keys <code>wg1</code>, not the HKDF: its
        256-bit output is the WireGuard PSK of the data tunnel, which runs inside{" "}
        <code>wg0</code>. The two keys protect nested tunnels rather than being
        combined into one. The IPsec lane&apos;s own arnika pair runs the same
        derivation, and its output becomes an RFC 8784 PPK instead of a
        WireGuard PSK; that lane has no Rosenpass.
      </p>
      <p style={{ color: "#6b7796", maxWidth: 720, fontSize: 12 }}>
        The first three widths ({KEY_FLOW_EDGES.filter((e) => e.illustrative).length} of{" "}
        {KEY_FLOW_EDGES.length} links, marked <code>illustrative</code> in
        <code> keyFlowGraph.ts</code>) show the <i>shape</i> of sifting and
        reconciliation at a readable scale. They are not the block sizes{" "}
        <Link to="/bb84">/bb84</Link> runs, and they are not measurements — read that
        page for real per-round counts. Everything from “QKD key” rightwards is
        the actual 256-bit key material.
      </p>
      {/* A PNG of the Sankey and the edge list behind it. Not animated: the
          figure is fixed, so a WebM or GIF would be a still. */}
      <div style={{ marginBottom: 12 }}>
        <ExportToolbar name="key-flow" animated={false}
                       pngTargetSelector="#keyflow-sankey"
                       jsonProvider={() => ({ nodes: KEY_FLOW_NODES, labels: KEY_FLOW_LABELS, edges: KEY_FLOW_EDGES })} />
      </div>
      <div id="keyflow-sankey">
      <Plot
        data={data}
        layout={{
          paper_bgcolor: "transparent", plot_bgcolor: "transparent",
          font: { color: "#d8e1ff", size: 13 },
          height: 420, margin: { l: 0, r: 0, t: 10, b: 10 },
        }}
        config={PLOT_CONFIG}
        style={{ width: "100%" }}
      />
      </div>
      <p style={{ color: "#9aa9d8", maxWidth: 760, fontSize: 12, marginBottom: 4 }}>
        The derivation, quoted from <code>submodules/arnika/kdf/kdf.go</code>. It
        builds the combined input in a separate slice rather than with{" "}
        <code>append(qkdKey, pqcKey...)</code>, which could write into the
        caller’s <code>qkdKey</code> backing array when it has spare capacity,
        and it zeroes the combined keying material inside a{" "}
        <code>secret.Do</code> block.
      </p>
      <pre style={{
        background: "#0d1320", border: "1px solid #1d2741", borderRadius: 8,
        padding: 14, color: "#cbd6f5", fontSize: 12, lineHeight: 1.55, marginTop: 4,
        overflowX: "auto",
      }}>
{`secret.Do(func() {
    // Build a combined input without mutating the caller's slices.
    combined := make([]byte, 0, len(qkdKey)+len(pqcKey))
    combined = append(combined, qkdKey...)
    combined = append(combined, pqcKey...)
    defer clear(combined)

    hkdf := hkdf.New(sha3.New256, combined, nil, nil)

    derivedKey := make([]byte, 32) // Output key length
    if _, err := io.ReadFull(hkdf, derivedKey); err != nil { ... }
    // derivedKey becomes the WireGuard PSK for this rotation interval
})`}
      </pre>
    </div>
  );
}
