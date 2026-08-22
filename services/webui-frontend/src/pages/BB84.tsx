import { useEffect, useRef, useState } from "react";
import Plot from "react-plotly.js";
import { Bb84Engine, type Bb84Frame } from "../lib/sim/bb84Sim";
import { BUNDLED_PARAMS, channelFromParams } from "../lib/sim/keyrate";
import ExportToolbar from "../components/ExportToolbar";

/**
 * BB84 Live — Round 5: the photon-level Monte-Carlo runs CLIENT-SIDE in a Web
 * Worker (or WebGPU compute shader when available), so a public demo puts NO
 * load on the backend. Channel params (η_total, e_d, Y0) come from the editable
 * config defaults; Eve controls reconfigure the engine live.
 */

/**
 * Offline defaults, which MUST equal `config/qkd_params.yaml`.
 *
 * That file calls itself the single source of truth for every numeric value,
 * and these had drifted from it: 25 km against a configured 10 km, and 1e7
 * against a configured 1e9 pulses per second -- a factor of 100. Since the
 * project recommends static hosting, where /api/sim/params is absent by
 * design, the offline path is a normal way to view this page, and it was
 * simulating a different physical link from every other component.
 *
 * tests/test_frontend_defaults_match_config.py compares these against the YAML
 * and fails on any divergence, because keeping two copies in step by hand is
 * what produced the drift.
 */
const DEFAULT_PARAMS = BUNDLED_PARAMS;

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
  const [qberThreshold, setQberThreshold] = useState(DEFAULT_PARAMS.qberThresholdAbort);
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
            qberThresholdAbort: j.protocol?.qber_threshold_abort ?? p.qberThresholdAbort,
          };
        }
      } catch { /* offline → bundled defaults */ }
      setQberThreshold(p.qberThresholdAbort);
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

  /**
   * Client-side run log. `logProvider`, never `logService`: this page's
   * Monte-Carlo runs entirely in the browser, so the server log says nothing
   * about the run and offering it under "Logs" would hand the user a
   * successful download of an unrelated file.
   */
  function runLog(): string {
    const lines = [
      "# BB84 live simulation run log",
      `# generated:   ${new Date().toISOString()}`,
      `# engine:      ${engineName}`,
      `# throughput:  ${pps.toLocaleString()} pulses/s`,
      `# eve:         ${eveOn ? `on, P(intercept)=${eveProb}` : "off"}`,
      `# abort thr.:  ${qberThreshold}`,
      `# rounds:      ${qberHistory.length}`,
      "#",
      "# round\tqber\tpool_size",
    ];
    qberHistory.forEach((q, i) => {
      lines.push(`${i}\t${q.toFixed(6)}\t${poolHistory[i] ?? ""}`);
    });
    lines.push("#", "# last photon frames (i, a_bit, a_basis, b_basis, b_bit, match)");
    frames.forEach((f) => {
      lines.push(
        `${f.i}\t${f.alice_bit}\t${f.alice_basis}\t${f.bob_basis}\t${f.bob_bit}\t${f.basis_match}`,
      );
    });
    return lines.join("\n") + "\n";
  }

  return (
    <div>
      <h2 style={{ marginTop: 0 }}>BB84 Live Simulation</h2>

      {/* This page produced QBER, key-pool and photon-frame data with no way to
          export any of it, while five other routes had a toolbar. */}
      <div style={{ marginBottom: 12 }}>
        <ExportToolbar
          name="bb84"
          logProvider={runLog}
          jsonProvider={() => ({
            engine: engineName,
            pulses_per_sec: pps,
            eve: { enabled: eveOn, intercept_probability: eveProb },
            qber_threshold_abort: qberThreshold,
            last_qber: lastQber,
            pool_size: pool,
            qber_history: qberHistory,
            pool_history: poolHistory,
            frames,
          })}
          csvProvider={() => qberHistory.map((q, i) => ({
            round: i, qber: q, pool_size: poolHistory[i] ?? null,
          }))}
        />
      </div>

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
              shapes: [{
                type: "line", x0: 0, x1: 1, xref: "paper",
                y0: qberThreshold, y1: qberThreshold,
                line: { dash: "dash", color: "#888" },
              }],
              annotations: [{
                xref: "paper", x: 1, xanchor: "right",
                y: qberThreshold, yanchor: "bottom", showarrow: false,
                text: `abort threshold ${(qberThreshold * 100).toFixed(1)} %`,
                font: { color: "#9aa9d8", size: 10 },
              }],
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
