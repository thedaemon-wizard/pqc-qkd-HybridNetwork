import { useEffect, useRef, useState } from "react";
import { isNewRound, reading } from "../lib/sim/benchmarksHistory";
import Plot from "react-plotly.js";
import { getStats } from "../api";
import KPI from "../components/KPI";
import PageHeader from "../components/PageHeader";
import ExportToolbar from "../components/ExportToolbar";

export default function Benchmarks() {
  const [roundMsHist, setRoundMsHist] = useState<number[]>([]);
  const [qberHist, setQberHist] = useState<number[]>([]);
  const [accepted, setAccepted] = useState(0);
  const [aborted, setAborted] = useState(0);

  // Round counter of the sample already plotted, so a poll that brings no new
  // round adds no point.
  const lastPlottedRound = useRef<number | null>(null);

  useEffect(() => {
    const t = setInterval(async () => {
      const s = await getStats();
      const a = s?.alice ?? {};
      setAccepted(a.rounds_accepted ?? 0);
      setAborted(a.rounds_aborted ?? 0);

      // Append per ROUND, not per poll.
      //
      // This used to push `a.last_qber ?? 0` on every tick regardless of
      // whether a round had happened, which made three things untrue at once:
      //
      //   * the charts are titled "round latency" and "QBER history" but were
      //     histories of POLLS -- with the pool full and rounds infrequent,
      //     most points were the same round resampled, drawing a flat line
      //     that reads as a stuck sensor;
      //   * "Avg QBER" and "Avg round ms" averaged those duplicates, so a
      //     value that stayed current for 60 s counted 60 times and one
      //     superseded in 1 s counted once -- a time-weighted mean presented
      //     as a per-round one;
      //   * `?? 0` substituted a zero for a MISSING field, and zero is a
      //     legitimate QBER (measured: the simqn backend returns
      //     [0.0, 0.029412, 0.009804] across three rounds), so a fabricated
      //     point was indistinguishable from a real one.
      if (!isNewRound(lastPlottedRound.current, a)) return;
      lastPlottedRound.current = a.rounds_total as number;

      // No `?? 0`: a round with no reading is dropped rather than recorded as
      // a perfect one.
      const ms = reading(a.last_round_ms);
      const qber = reading(a.last_qber);
      if (ms !== null) setRoundMsHist((h) => [...h.slice(-119), ms]);
      if (qber !== null) setQberHist((h) => [...h.slice(-119), qber]);
    }, 1000);
    return () => clearInterval(t);
  }, []);

  return (
    <div>
      <PageHeader
        title="Benchmarks"
        subtitle="Live BB84 round latency and QBER history."
      />
      <div style={{ marginBottom: 12 }}>
        <ExportToolbar
          name="benchmarks"
          logService="alice"
          jsonProvider={() => ({ accepted, aborted, roundMsHist, qberHist })}
          csvProvider={() => roundMsHist.map((ms, i) => ({
            i, round_ms: ms, qber: qberHist[i] ?? null,
          }))}
        />
      </div>

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

const common: any = {
  paper_bgcolor: "transparent", plot_bgcolor: "transparent",
  margin: { l: 50, r: 10, t: 30, b: 30 },
  font: { color: "#9aa9d8" },
};
