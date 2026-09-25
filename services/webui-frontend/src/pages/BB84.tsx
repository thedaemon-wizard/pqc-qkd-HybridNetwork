import { useEffect, useRef, useState } from "react";
import Plot from "react-plotly.js";
import { PLOT_CONFIG } from "../lib/plotConfig";
import { Bb84Engine, type TierTrial, type Bb84Frame } from "../lib/sim/bb84Sim";
import { engineChoiceSummary } from "../lib/sim/engineChoice";
import { BUNDLED_PARAMS, channelFromParams } from "../lib/sim/keyrate";
import { seedFromLocation } from "../lib/sim/runSeed";
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

/**
 * Where the intercept slider starts when Eve is switched on. A UI choice, not
 * a configured value: config's `eve.intercept_prob` is 0.0 because the backend
 * simulator runs with Eve off, and starting the slider there would make the
 * Eve toggle visibly do nothing.
 */
const EVE_SLIDER_START = 1.0;

/** Rounds kept for the charts and the exports; `roundsTotal` counts them all. */
const HISTORY_ROUNDS = 60;

/**
 * The Shor-Preskill BB84 bound, about 11 %. The chart names it only when the
 * configured ceiling IS it: the label said "Shor-Preskill" whatever
 * protocol.qber_threshold_abort was set to. Half a per-mille of tolerance
 * covers the rounding of a hand-entered 0.11.
 */
const SHOR_PRESKILL_QBER = 0.11;
const SHOR_PRESKILL_TOLERANCE = 0.0005;

export default function BB84() {
  // Read once; the URL does not change under the page.
  const pinnedSeed = seedFromLocation();
  // null entries are rounds that sifted nothing: no QBER was measured.
  const [qberHistory, setQberHistory] = useState<(number | null)[]>([]);
  /** Rounds since the page loaded; the histories hold the last HISTORY_ROUNDS. */
  const [roundsTotal, setRoundsTotal] = useState(0);
  const [poolHistory, setPoolHistory] = useState<number[]>([]);
  const [frames, setFrames] = useState<Bb84Frame[]>([]);
  const [eveOn, setEveOn] = useState(false);
  const [eveProb, setEveProb] = useState(EVE_SLIDER_START);
  const [engineName, setEngineName] = useState("starting…");
  // null until the engine reports: a 0 here printed "0.0M pulses/s" and
  // `last_qber: 0` before the first round, which read as measurements.
  const [pps, setPps] = useState<number | null>(null);
  const [lastQber, setLastQber] = useState<number | null>(null);
  const [pool, setPool] = useState(0);
  const [tierTrials, setTierTrials] = useState<TierTrial[]>([]);
  const [workerPps, setWorkerPps] = useState<number | null>(null);
  const [qberThreshold, setQberThreshold] = useState(DEFAULT_PARAMS.qberThresholdAbort);
  const engineRef = useRef<Bb84Engine | null>(null);

  useEffect(() => {
    const eng = new Bb84Engine((u) => {
      setQberHistory((h) => [...h.slice(-(HISTORY_ROUNDS - 1)), u.qber]);
      setPoolHistory((h) => [...h.slice(-(HISTORY_ROUNDS - 1)), u.pool_size]);
      setRoundsTotal((n) => n + 1);
      setFrames(u.frames);
      setEngineName(u.engine);
      setPps(u.pulsesPerSec);
      setLastQber(u.qber);
      setPool(u.pool_size);
      setTierTrials(u.tierTrials);
      setWorkerPps(u.workerPulsesPerSec);
    });
    engineRef.current = eng;
    // Load editable config defaults (falls back to bundled defaults offline).
    (async () => {
      let p = DEFAULT_PARAMS;
      try {
        const r = await fetch("/api/sim/params");
        if (r.ok) {
          const j = await r.json();
          // Spread first: BB84 only needs the seven channel fields, but
          // BUNDLED_PARAMS now carries all fifteen editable ones for
          // /physics. Rebuilding the object from scratch would drop the other
          // eight and change its type.
          p = {
            ...p,
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
      eng.setConfig({ etaTotal, Y0, eD: p.misalignmentErrorEd, eveOn, eveProb,
                      qberAbort: p.qberThresholdAbort });
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
      `# throughput:  ${pps === null ? "(not reported yet)" : pps.toLocaleString()} pulses/s`,
      `# eve:         ${eveOn ? `on, P(intercept)=${eveProb}` : "off"}`,
      `# abort thr.:  ${qberThreshold}`,
      // The window, and the whole run: the table below is the last rounds
      // only, numbered by their round in the run, not from 0 in the window.
      `# rounds:      last ${qberHistory.length} of ${roundsTotal}`,
      "#",
      "# round\tqber\tpool_size",
    ];
    const first = roundsTotal - qberHistory.length;
    qberHistory.forEach((q, i) => {
      lines.push(`${first + i}\t${q === null ? "n/a (nothing sifted)" : q.toFixed(6)}\t${poolHistory[i] ?? ""}`);
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
            // Which accelerators were benchmarked and what they scored. The
            // export is the citable artefact, so "the CPU won" has to be
            // recoverable from it and not only from the screen.
            accelerator_trials: tierTrials,
            worker_pulses_per_sec: workerPps,
            eve: { enabled: eveOn, intercept_probability: eveProb },
            qber_threshold_abort: qberThreshold,
            last_qber: lastQber,
            pool_size: pool,
            rounds_total: roundsTotal,
            qber_history: qberHistory,
            pool_history: poolHistory,
            frames,
          })}
          csvProvider={() => qberHistory.map((q, i) => ({
            round: roundsTotal - qberHistory.length + i, qber: q, pool_size: poolHistory[i] ?? null,
          }))}
        />
      </div>

      {/* The channel this page samples, stated. docs/keyrate.md's model is a
          weak-coherent source with mean photon number mu; the four engines
          here draw one photon per pulse and give a dark count Alice's bit. */}
      <p style={{ color: "#9aa9d8", fontSize: 12, maxWidth: 760, margin: "0 0 12px" }}>
        This Monte-Carlo models an <b>ideal single-photon source</b>: each pulse is
        detected with probability &eta;<sub>total</sub> + Y<sub>0</sub>, and a detection
        carries Alice&apos;s bit with misalignment error e<sub>d</sub>, dark counts included.
        It is not the weak-coherent decoy-state channel of <code>docs/keyrate.md</code>{" "}
        (Q<sub>&mu;</sub> = Y<sub>0</sub> + 1 &minus; e<sup>&minus;&eta;&mu;</sup>, dark counts
        at 50 % error) that <code>/physics</code> computes, so its gain and QBER are not
        that model&apos;s, especially at long distance where dark counts dominate.
      </p>

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
                        borderRadius: 10, padding: "2px 10px" }}
              title={engineChoiceSummary(tierTrials, workerPps)}>
          ⚡ {engineName} · {pps === null ? "—" : `${(pps / 1e6).toFixed(1)}M`} pulses/s
        </span>
      </div>

      {/*
        Which accelerators were tried, and what they scored.

        This was measured and then discarded to `console.info`, so the badge
        above read `Worker (CPU)` and a reader concluded the WebGPU compute
        shader did not exist. It does; on the demo host it benchmarked
        33-50 M/s against the CPU worker's 42-61 M/s and correctly lost. That
        is a result worth showing -- "we tried the GPU and the CPU was faster"
        is a different statement from "there is no GPU path", and only one of
        them is true here.
      */}
      {tierTrials.length > 0 && (
        <div style={{ fontSize: 11, color: "#6b7796", marginBottom: 12 }}>
          Accelerator selection (measured in your browser
          {workerPps !== null && `, CPU worker ${(workerPps / 1e6).toFixed(1)}M/s`}):{" "}
          {tierTrials.map((t, i) => (
            <span key={`${t.tier}-${i}`}>
              {i > 0 && " · "}
              <b style={{ color: t.adopted ? "#3ddc84" : "#8d9ac4" }}>{t.tier}</b>{" "}
              {t.pulsesPerSec !== null
                ? `${(t.pulsesPerSec / 1e6).toFixed(1)}M/s ${t.adopted ? "— adopted" : "— slower, not adopted"}`
                : `— ${t.error ?? "no result"}`}
            </span>
          ))}
        </div>
      )}

      {/* Plots */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
        <ChartCard title={`QBER (last ${HISTORY_ROUNDS} rounds; gaps are rounds that sifted nothing)`}>
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
                // "hard abort ceiling", not "abort threshold". Crossing this line
                // aborts, but staying under it does NOT mean a round is accepted:
                // the backend also requires a positive modelled key rate, which
                // vanishes at QBER 1.505 % (Lim finite-key, N = 1e9) -- far below.
                // config/qkd_params.yaml states this; the chart did not, so a
                // reader watching Eve push QBER to 0.257 with nothing happening
                // had no way to know which of the two conditions this line is.
                text: `hard abort ceiling ${(qberThreshold * 100).toFixed(1)} % (`
                  + (Math.abs(qberThreshold - SHOR_PRESKILL_QBER) < SHOR_PRESKILL_TOLERANCE ? "Shor-Preskill; " : "")
                  + "not the accept criterion)",
                font: { color: "#9aa9d8", size: 10 },
              }],
            }}
            config={PLOT_CONFIG}
            style={{ width: "100%" }}
          />
        </ChartCard>
        <ChartCard title="Key pool (bits)">
          <Plot
            data={[{ y: poolHistory, type: "scatter", mode: "lines", line: { color: "#3ddc84" }, fill: "tozeroy" }]}
            layout={{ ...plotLayout, height: 240, yaxis: { color: "#9aa9d8" } }}
            config={PLOT_CONFIG}
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
  // Present only when the run is reproducible. Absent is the honest value
  // for an unpinned run: reporting `seed: null` beside real numbers invites
  // the reading that a seed was used and happened to be null.
  ...(pinnedSeed !== null ? { seed: pinnedSeed, reproducible: true } : {}),
  pulses_per_sec: pps,
  last_qber: lastQber === null ? null : Number(lastQber.toFixed(4)),
  key_pool_bits: pool,
  rounds: roundsTotal,
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
