import Plot from "react-plotly.js";
import { KEY_FLOW_EDGES, KEY_FLOW_NODES, toSankeyLinks } from "./keyFlowGraph";

/**
 * Hybrid key derivation flow.
 *
 * The graph is defined in keyFlowGraph.ts as a named edge list and checked by
 * keyFlowGraph.test.ts. It used to be three parallel arrays inline here, and in
 * that form the "WireGuard PSK" node was referenced by no edge at all -- the one
 * arrow the paragraph below promises was the only one the figure did not draw.
 * See that file for the full reading.
 */
export default function KeyFlow() {
  const links = toSankeyLinks();
  const nodeColor = ["#3ddc84", "#3ddc84", "#3ddc84", "#3ddc84",
                     "#7c5cff", "#7c5cff", "#ff9442", "#5b8def"];
  // Colour each link by its SOURCE, so the lane a flow belongs to is derived
  // rather than maintained as a fourth parallel array that can fall out of step.
  const linkColor = links.source.map((i) => `${nodeColor[i]}70`);

  const data: any = [{
    type: "sankey",
    orientation: "h",
    node: {
      pad: 24,
      thickness: 22,
      label: [...KEY_FLOW_NODES],
      color: nodeColor,
    },
    link: { ...links, color: linkColor },
  }];

  return (
    <div>
      <h2 style={{ marginTop: 0 }}>Hybrid Key Derivation Flow</h2>
      <p style={{ color: "#9aa9d8", maxWidth: 720 }}>
        The QKD lane (green) and the PQC lane (purple) are fused by HKDF-SHA3-256
        (orange) into the 256-bit WireGuard PSK. <b>Widths are bits</b> — the two
        256-bit inputs give 512 bits of keying material, and HKDF emits 256; that
        narrowing at the orange node is the derivation, not a drawing error.
      </p>
      <p style={{ color: "#6b7796", maxWidth: 720, fontSize: 12 }}>
        The first three widths ({KEY_FLOW_EDGES.filter((e) => e.illustrative).length} of{" "}
        {KEY_FLOW_EDGES.length} links, marked <code>illustrative</code> in
        <code> keyFlowGraph.ts</code>) show the <i>shape</i> of sifting and
        reconciliation at a readable scale. They are not the block sizes{" "}
        <a href="/bb84">/bb84</a> runs, and they are not measurements — read that
        page for real per-round counts. Everything from “QKD key” rightwards is
        the actual 256-bit key material.
      </p>
      <Plot
        data={data}
        layout={{
          paper_bgcolor: "transparent", plot_bgcolor: "transparent",
          font: { color: "#d8e1ff", size: 13 },
          height: 420, margin: { l: 0, r: 0, t: 10, b: 10 },
        }}
        config={{ displaylogo: false }}
        style={{ width: "100%" }}
      />
      <p style={{ color: "#9aa9d8", maxWidth: 760, fontSize: 12, marginBottom: 4 }}>
        The derivation, from <code>submodules/arnika/kdf/kdf.go</code>. This block
        previously showed{" "}
        <code>hkdf.New(sha3.New256, append(qkdKey, pqcKey...), nil, nil)</code>{" "}
        under the same citation. That is not what the file does, and the
        difference is the point:{" "}
        <code>append(qkdKey, pqcKey...)</code> can write into the caller’s{" "}
        <code>qkdKey</code> backing array when it has spare capacity, which is
        the aliasing the real code builds a separate slice to avoid — and the
        snippet also dropped the <code>secret.Do</code> block that zeroes the
        combined keying material.
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
