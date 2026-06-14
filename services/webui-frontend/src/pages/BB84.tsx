import { useEffect, useRef, useState } from "react";
import Plot from "react-plotly.js";
import { Bb84Engine, type Bb84Frame } from "../lib/sim/bb84Sim";
import { channelFromParams } from "../lib/sim/keyrate";

/**
 * BB84 Live — Round 5: the photon-level Monte-Carlo runs CLIENT-SIDE in a Web
 * Worker (or WebGPU compute shader when available), so a public demo puts NO
 * load on the backend. Channel params (η_total, e_d, Y0) come from the editable
 * config defaults; Eve controls reconfigure the engine live.
 */

// Bundled fallback defaults (used if the backend /api/sim/params is absent).
const DEFAULT_PARAMS = {
  detectorEfficiency: 0.2, fiberAttenuationDbPerKm: 0.2, linkLengthKm: 25,
  darkCountRateHz: 100, pulseRateHz: 1e7, misalignmentErrorEd: 0.015,
};

export default function BB84() {
  const [qberHistory, setQberHistory] = useState<number[]>([]);
  const [poolHistory, setPoolHistory] = useState<number[]>([]);
  const [frames, setFrames] = useState<Bb84Frame[]>([]);
  const [eveOn, setEveOn] = useState(false);
  const [eveProb, setEveProb] = useState(1.0);
  const [engineName, setEngineName] = useState("starting…");
  const [pps, setPps] = useState(0);
  const [lastQber, setLastQber] = useState(0);
  const [pool, setPool] = useState(0);
  const engineRef = useRef<Bb84Engine | null>(null);

  useEffect(() => {
    const eng = new Bb84Engine((u) => {
      setQberHistory((h) => [...h.slice(-59), u.qber]);
      setPoolHistory((h) => [...h.slice(-59), u.pool_size]);
      setFrames(u.frames);
      setEngineName(u.engine);
      setPps(u.pulsesPerSec);
      setLastQber(u.qber);
      setPool(u.pool_size);
    });
    engineRef.current = eng;
    // Load editable config defaults (falls back to bundled defaults offline).
    (async () => {
      let p = DEFAULT_PARAMS;
      try {
        const r = await fetch("/api/sim/params");
        if (r.ok) {
          const j = await r.json();
          p = {
            detectorEfficiency: j.physical?.detector_efficiency ?? p.detectorEfficiency,
            fiberAttenuationDbPerKm: j.physical?.fiber_attenuation_db_per_km ?? p.fiberAttenuationDbPerKm,
            linkLengthKm: j.physical?.link_length_km ?? p.linkLengthKm,
            darkCountRateHz: j.physical?.dark_count_rate_hz ?? p.darkCountRateHz,
            pulseRateHz: j.source?.pulse_rate_hz ?? p.pulseRateHz,
            misalignmentErrorEd: j.physical?.misalignment_error_ed ?? p.misalignmentErrorEd,
          };
        }
      } catch { /* offline → bundled defaults */ }
      const { etaTotal, Y0 } = channelFromParams(p);
      eng.setConfig({ etaTotal, Y0, eD: p.misalignmentErrorEd, eveOn, eveProb });
      eng.start();
    })();
    return () => eng.dispose();
  }, []);

  function updateEve(on: boolean, prob: number) {
    setEveOn(on); setEveProb(prob);
    engineRef.current?.setConfig({ eveOn: on, eveProb: prob });
  }

  return (
    <div>
      <h2 style={{ marginTop: 0 }}>BB84 Live Simulation</h2>

      {/* Controls */}
      <div style={{ display: "flex", gap: 12, alignItems: "center", marginBottom: 16, flexWrap: "wrap" }}>
        <label style={{ fontSize: 13 }}>
          <input type="checkbox" checked={eveOn}
                 onChange={(e) => updateEve(e.target.checked, eveProb)} />
          {" "}Enable Eve (intercept-resend)
        </label>
        <label style={{ fontSize: 13 }}>
          P(intercept) {eveProb.toFixed(2)}{" "}
          <input type="range" min={0} max={1} step={0.05} value={eveProb}
                 onChange={(e) => updateEve(eveOn, parseFloat(e.target.value))} />
        </label>
        <span style={{ fontSize: 11, color: "#3ddc84", border: "1px solid #1d4030",
                        borderRadius: 10, padding: "2px 10px" }}>
          ⚡ {engineName} · {(pps / 1e6).toFixed(1)}M pulses/s
        </span>
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
        <ChartCard title="Live engine stats (client-side)">
          <pre style={{ margin: 0, fontSize: 12, lineHeight: 1.5, color: "#cbd6f5" }}>
{JSON.stringify({
  engine: engineName,
  pulses_per_sec: pps,
  last_qber: Number(lastQber.toFixed(4)),
  key_pool: pool,
  eve: eveOn ? `on (p=${eveProb.toFixed(2)})` : "off",
}, null, 2)}
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
