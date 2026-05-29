import { useEffect, useState } from "react";
import Plot from "react-plotly.js";
import { getStats } from "../api";

export default function Benchmarks() {
  const [roundMsHist, setRoundMsHist] = useState<number[]>([]);
  const [qberHist, setQberHist] = useState<number[]>([]);
  const [accepted, setAccepted] = useState(0);
  const [aborted, setAborted] = useState(0);

  useEffect(() => {
    const t = setInterval(async () => {
      const s = await getStats();
      const a = s?.alice ?? {};
      setRoundMsHist((h) => [...h.slice(-119), a.last_round_ms ?? 0]);
      setQberHist((h) => [...h.slice(-119), a.last_qber ?? 0]);
      setAccepted(a.rounds_accepted ?? 0);
      setAborted(a.rounds_aborted ?? 0);
    }, 1000);
    return () => clearInterval(t);
  }, []);

  return (
    <div>
      <h2 style={{ marginTop: 0 }}>Benchmarks</h2>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 12, marginBottom: 16 }}>
        <KPI label="Rounds accepted" value={accepted} />
        <KPI label="Rounds aborted" value={aborted} />
        <KPI label="Avg round ms" value={roundMsHist.length ? (roundMsHist.reduce((a,b)=>a+b,0) / roundMsHist.length).toFixed(0) : "—"} />
        <KPI label="Avg QBER" value={qberHist.length ? (qberHist.reduce((a,b)=>a+b,0) / qberHist.length).toFixed(3) : "—"} />
      </div>

      <Plot
        data={[
          { y: roundMsHist, type: "scatter", mode: "lines", name: "round ms", line: { color: "#5b8def" } },
        ]}
        layout={{
          ...common, height: 260,
          title: { text: "BB84 round latency (ms)", font: { color: "#9aa9d8", size: 14 } },
        }}
        style={{ width: "100%" }}
        config={{ displaylogo: false }}
      />
      <Plot
        data={[
          { y: qberHist, type: "scatter", mode: "lines", name: "QBER", line: { color: "#ff5e7e" }, fill: "tozeroy" },
        ]}
        layout={{
          ...common, height: 260, yaxis: { range: [0, 0.5], color: "#9aa9d8" },
          title: { text: "QBER history", font: { color: "#9aa9d8", size: 14 } },
        }}
        style={{ width: "100%" }}
        config={{ displaylogo: false }}
      />
    </div>
  );
}

function KPI({ label, value }: { label: string; value: any }) {
  return (
    <div style={{ background: "#0d1320", border: "1px solid #1d2741", borderRadius: 8, padding: 12 }}>
      <div style={{ fontSize: 11, color: "#6b7796", marginBottom: 4 }}>{label}</div>
      <div style={{ fontSize: 22, color: "#d8e1ff", fontWeight: 700 }}>{value}</div>
    </div>
  );
}

const common: any = {
  paper_bgcolor: "transparent", plot_bgcolor: "transparent",
  margin: { l: 50, r: 10, t: 30, b: 30 },
  font: { color: "#9aa9d8" },
};
