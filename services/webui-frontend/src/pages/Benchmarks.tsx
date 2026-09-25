import { useRef, useState } from "react";
import {
  appendRound, benchmarksCsvRows, isNewRound, reading, type RoundRec,
} from "../lib/sim/benchmarksHistory";
import { usePoll } from "../lib/usePoll";
import Plot from "react-plotly.js";
import { PLOT_CONFIG } from "../lib/plotConfig";
import { getStats } from "../api";
import KPI from "../components/KPI";
import PageHeader from "../components/PageHeader";
import ExportToolbar from "../components/ExportToolbar";

/** The KME this page reports. Named once, used everywhere, exported. */
const BENCH_NODE = "alice" as const;

export default function Benchmarks() {
  const [rounds, setRounds] = useState<RoundRec[]>([]);
  const roundMsHist = rounds.filter((r) => r.ms !== null);
  const qberHist = rounds.filter((r) => r.qber !== null);
  // `null` until a poll actually reports the counters. `useState(0)` made an
  // unreachable KME render "Rounds accepted 0", which is also what a reachable
  // KME that has run zero rounds renders -- and that difference is the whole
  // question this page answers.
  const [accepted, setAccepted] = useState<number | null>(null);
  const [aborted, setAborted] = useState<number | null>(null);
  // Provenance, which /api/stats has published all along and this page threw
  // away. The service says whether the last round was SIMULATED
  // (`last_round_synthetic`), whether the rate is modelled rather than measured
  // (`skr_provenance`), and since the config-generation change whether that
  // rate still reflects the current parameters (`skr_reflects_current_config`).
  // None of it reached the screen or the export, so the page laundered a
  // synthetic, possibly stale model into what reads as a measurement.
  const [prov, setProv] = useState<{
    synthetic: boolean | null; current: boolean | null;
    modelledBps: number | null; provenance: string | null;
  }>({ synthetic: null, current: null, modelledBps: null, provenance: null });

  // Round counter of the sample already plotted, so a poll that brings no new
  // round adds no point.
  const lastPlottedRound = useRef<number | null>(null);

  // Distinct from the per-field absence handling below. `reading()` covers
  // "the backend answered but the KME did not"; this covers "the backend did
  // not answer at all", which used to reject unhandled INSIDE a 1 s interval
  // -- so a static deploy produced one console error per second and the page
  // kept rendering its last values as though they were current.
  const [unreachable, setUnreachable] = useState<string | null>(null);

  usePoll(async () => {
      let s: Awaited<ReturnType<typeof getStats>>;
      try {
        s = await getStats();
        setUnreachable(null);
      } catch (e) {
        setUnreachable(String((e as Error)?.message ?? e));
        return;
      }
      // `/api/stats` answers `{"alice": {"error": "..."}}` when the KME is
      // unreachable (see stats() in services/webui-backend/app/main.py), so
      // `rounds_accepted` is simply absent. `?? 0` reported that absence as a
      // measurement of zero -- the very substitution the comment below rejects
      // for QBER. Same rule, same helper.
      // NAMED, not implicit. The two KMEs diverge -- measured on the live demo
      // 2026-08-28, alice had run 36 rounds and bob 6 -- so plotting one
      // without saying which is a chart of an unidentified node.
      const a = s?.[BENCH_NODE] ?? {};
      setAccepted(reading(a.rounds_accepted));
      setAborted(reading(a.rounds_aborted));
      setProv({
        synthetic: typeof a.last_round_synthetic === "boolean"
          ? a.last_round_synthetic : null,
        current: typeof a.skr_reflects_current_config === "boolean"
          ? a.skr_reflects_current_config : null,
        modelledBps: typeof a.modelled_skr_bps === "number"
          ? a.modelled_skr_bps : null,
        provenance: typeof a.skr_provenance === "string"
          ? a.skr_provenance : null,
      });

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
      if (ms === null && qber === null) return;
      setRounds((h) => appendRound(h, { round: a.rounds_total as number, ms, qber }));
  }, 1000);

  return (
    <div>
      <PageHeader
        title="Benchmarks"
        subtitle="Live BB84 round latency and QBER history."
      />
      {unreachable && (
        <p style={{ color: "#e0777d", margin: "0 0 12px" }}>
          Not observed &mdash; <code>GET /api/stats</code> failed: {unreachable}.
          The figures below are the last successful poll, not current.
        </p>
      )}
      <div style={{ marginBottom: 12 }}>
        <ExportToolbar
          name="benchmarks"
          logService="alice"
          jsonProvider={() => ({
            // The node and the provenance travel WITH the numbers. An export
            // of four arrays with no node, no backend and no synthetic flag is
            // not citable evidence of anything.
            node: BENCH_NODE,
            accepted, aborted, rounds,
            last_round_synthetic: prov.synthetic,
            modelled_skr_bps: prov.modelledBps,
            skr_provenance: prov.provenance,
            skr_reflects_current_config: prov.current,
          })}
          csvProvider={() => benchmarksCsvRows(rounds)}
        />
      </div>

      <p style={{ color: "#9aa9d8", fontSize: 12, maxWidth: 820, marginTop: 0 }}>
        Counters for <b>{BENCH_NODE}</b>. The two KMEs run independently and
        their round counts diverge, so this is one node, named, not a total.{" "}
        {prov.synthetic === true && (
          <b style={{ color: "#f5a623" }}>
            The last round was SIMULATED, not measured — the backend
            under-produced and the stream was synthesised from the configured
            physics.{" "}
          </b>
        )}
        {prov.modelledBps !== null && (
          <>
            The rate below it, {prov.modelledBps.toExponential(3)} bps, is{" "}
            {prov.provenance ?? "modelled from config"}
            {prov.current === false && (
              <b style={{ color: "#f5a623" }}>
                {" "}and predates the current parameters — no round has run
                since they changed
              </b>
            )}
            .
          </>
        )}
      </p>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 12, marginBottom: 16 }}>
        <KPI label="Rounds accepted" value={accepted ?? "—"} />
        <KPI label="Rounds aborted" value={aborted ?? "—"} />
        <KPI label="Avg round ms" value={roundMsHist.length ? (roundMsHist.reduce((a, b) => a + b.ms!, 0) / roundMsHist.length).toFixed(0) : "—"} />
        <KPI label="Avg QBER" value={qberHist.length ? (qberHist.reduce((a, b) => a + b.qber!, 0) / qberHist.length).toFixed(3) : "—"} />
      </div>

      <Plot
        data={[
          { x: roundMsHist.map((r) => r.round), y: roundMsHist.map((r) => r.ms), type: "scatter", mode: "lines", name: "round ms", line: { color: "#5b8def" } },
        ]}
        layout={{
          ...common, height: 260,
          title: { text: "BB84 round latency (ms)", font: { color: "#9aa9d8", size: 14 } },
        }}
        style={{ width: "100%" }}
        config={PLOT_CONFIG}
      />
      <Plot
        data={[
          { x: qberHist.map((r) => r.round), y: qberHist.map((r) => r.qber), type: "scatter", mode: "lines", name: "QBER", line: { color: "#ff5e7e" }, fill: "tozeroy" },
        ]}
        layout={{
          ...common, height: 260, yaxis: { range: [0, 0.5], color: "#9aa9d8" },
          title: { text: "QBER history", font: { color: "#9aa9d8", size: 14 } },
        }}
        style={{ width: "100%" }}
        config={PLOT_CONFIG}
      />
    </div>
  );
}

const common: any = {
  paper_bgcolor: "transparent", plot_bgcolor: "transparent",
  margin: { l: 50, r: 10, t: 30, b: 30 },
  font: { color: "#9aa9d8" },
};
