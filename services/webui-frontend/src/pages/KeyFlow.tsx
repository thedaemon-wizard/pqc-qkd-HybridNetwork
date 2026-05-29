import Plot from "react-plotly.js";

export default function KeyFlow() {
  // Static Sankey representing the HKDF combination flow.
  // Animation: in a follow-up we'll subscribe to PSK rotation events and recolor.
  const data: any = [{
    type: "sankey",
    orientation: "h",
    node: {
      pad: 24,
      thickness: 22,
      label: [
        "BB84 raw bits",          // 0
        "Sifted (basis-match)",   // 1
        "Reconciled (QBER ok)",   // 2
        "QKD key (256b)",         // 3
        "Rosenpass ML-KEM-768",   // 4
        "PQC key (256b)",         // 5
        "HKDF-SHA3-256",          // 6
        "WireGuard PSK",          // 7
      ],
      color: ["#3ddc84", "#3ddc84", "#3ddc84", "#3ddc84",
              "#7c5cff", "#7c5cff",
              "#ff9442",
              "#5b8def"],
    },
    link: {
      source: [0, 1, 2, 3, 4, 5, 3, 5],
      target: [1, 2, 3, 6, 5, 6, 6, 6],
      value:  [200, 120, 100, 32, 256, 32, 32, 32],
      color:  ["#3ddc8430","#3ddc8430","#3ddc8430","#3ddc8470",
               "#7c5cff30","#7c5cff70","#3ddc8470","#7c5cff70"],
    },
  }];

  return (
    <div>
      <h2 style={{ marginTop: 0 }}>Hybrid Key Derivation Flow</h2>
      <p style={{ color: "#9aa9d8", maxWidth: 720 }}>
        QKD レーン (緑) と PQC レーン (紫) は HKDF-SHA3-256 (橙) で融合され、32 バイトの WireGuard PSK となる。
        参考: <code>submodules/arnika-vq/kdf/kdf.go:12-27</code>
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
      <pre style={{
        background: "#0d1320", border: "1px solid #1d2741", borderRadius: 8,
        padding: 14, color: "#cbd6f5", fontSize: 12, lineHeight: 1.55, marginTop: 12,
      }}>
{`hkdf := hkdf.New(sha3.New256, append(qkdKey, pqcKey...), nil, nil)
derived := make([]byte, 32)
io.ReadFull(hkdf, derived)
// derived[] becomes the WireGuard PSK for this rotation interval`}
      </pre>
    </div>
  );
}
