import { useEffect, useRef, useState } from "react";
import Plot from "react-plotly.js";
import { getStats, openFramesWS, postEve, postRotate } from "../api";

type Frame = {
  i: number; alice_bit: number; alice_basis: number;
  bob_basis: number; bob_bit: number; basis_match: boolean;
};

export default function BB84() {
  const [qberHistory, setQberHistory] = useState<number[]>([]);
  const [poolHistory, setPoolHistory] = useState<number[]>([]);
  const [frames, setFrames] = useState<Frame[]>([]);
  const [eveOn, setEveOn] = useState(false);
  const [eveProb, setEveProb] = useState(1.0);
  const [stats, setStats] = useState<any>({});
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    wsRef.current = openFramesWS((d) => {
      if (d.type === "frames") {
        setQberHistory((h) => [...h.slice(-59), d.qber]);
        setPoolHistory((h) => [...h.slice(-59), d.pool_size]);
        setFrames(d.frames || []);
      }
    });
    const t = setInterval(async () => setStats(await getStats()), 1500);
    return () => { wsRef.current?.close(); clearInterval(t); };
  }, []);

  return (
    <div>
      <h2 style={{ marginTop: 0 }}>BB84 Live Simulation</h2>

      {/* Controls */}
      <div style={{ display: "flex", gap: 12, alignItems: "center", marginBottom: 16, flexWrap: "wrap" }}>
        <label style={{ fontSize: 13 }}>
          <input type="checkbox" checked={eveOn}
                 onChange={async (e) => { setEveOn(e.target.checked); await postEve(e.target.checked, eveProb); }} />
          {" "}Enable Eve (intercept-resend)
        </label>
        <label style={{ fontSize: 13 }}>
          P(intercept) {eveProb.toFixed(2)}{" "}
          <input type="range" min={0} max={1} step={0.05} value={eveProb}
                 onChange={async (e) => {
                   const v = parseFloat(e.target.value); setEveProb(v);
                   if (eveOn) await postEve(true, v);
                 }} />
        </label>
        <button onClick={() => postRotate()} style={btnStyle}>Force rotate</button>
      </div>

      {/* Plots */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
        <ChartCard title="QBER (last 60 rounds)">
          <Plot
            data={[{ y: qberHistory, type: "scatter", mode: "lines+markers", line: { color: "#ff5e7e" } }]}
            layout={{
              ...plotLayout, height: 240,
              yaxis: { range: [0, 0.5], color: "#9aa9d8" },
              shapes: [{ type: "line", x0: 0, x1: 1, xref: "paper", y0: 0.11, y1: 0.11, line: { dash: "dash", color: "#888" } }],
            }}
            config={{ displaylogo: false }}
            style={{ width: "100%" }}
          />
        </ChartCard>
        <ChartCard title="Key pool size">
          <Plot
            data={[{ y: poolHistory, type: "scatter", mode: "lines", line: { color: "#3ddc84" }, fill: "tozeroy" }]}
            layout={{ ...plotLayout, height: 240, yaxis: { color: "#9aa9d8" } }}
            config={{ displaylogo: false }}
            style={{ width: "100%" }}
          />
        </ChartCard>
      </div>

      {/* Frames + stats */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16, marginTop: 16 }}>
        <ChartCard title="Sample photon frames">
          <table style={{ width: "100%", fontSize: 12, color: "#d8e1ff" }}>
            <thead>
              <tr style={{ color: "#6b7796" }}>
                <th>#</th><th>A bit</th><th>A basis</th><th>B basis</th><th>B bit</th><th>Match</th>
              </tr>
            </thead>
            <tbody>
              {frames.slice(0, 14).map((f) => (
                <tr key={f.i} style={{ background: f.basis_match ? "transparent" : "#1a1124" }}>
                  <td>{f.i}</td>
                  <td>{f.alice_bit}</td>
                  <td>{f.alice_basis === 0 ? "+" : "x"}</td>
                  <td>{f.bob_basis === 0 ? "+" : "x"}</td>
                  <td style={{ color: f.alice_bit !== f.bob_bit && f.basis_match ? "#ff5e7e" : "#d8e1ff" }}>{f.bob_bit}</td>
                  <td>{f.basis_match ? "✓" : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </ChartCard>
        <ChartCard title="Live stats (Alice KME)">
          <pre style={{ margin: 0, fontSize: 12, lineHeight: 1.5, color: "#cbd6f5" }}>
{JSON.stringify(stats?.alice ?? {}, null, 2)}
          </pre>
        </ChartCard>
      </div>
    </div>
  );
}

function ChartCard({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div style={{ background: "#0d1320", border: "1px solid #1d2741", borderRadius: 8, padding: 12 }}>
      <h3 style={{ margin: "0 0 8px 0", fontSize: 14, color: "#9aa9d8" }}>{title}</h3>
      {children}
    </div>
  );
}

const plotLayout: any = {
  paper_bgcolor: "transparent", plot_bgcolor: "transparent",
  margin: { l: 40, r: 10, t: 10, b: 30 },
  font: { color: "#9aa9d8" },
};

const btnStyle: React.CSSProperties = {
  background: "#1a2440", color: "#d8e1ff", border: "1px solid #2a3760",
  borderRadius: 4, padding: "4px 12px", fontSize: 12, cursor: "pointer",
};
