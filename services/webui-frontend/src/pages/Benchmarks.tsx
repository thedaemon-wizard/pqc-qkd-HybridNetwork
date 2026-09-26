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
import { NARROW_COLUMN, useNarrowLayout } from "../lib/layout";

/** The KME this page reports. Named once, used everywhere, exported. */
const BENCH_NODE = "alice" as const;

/** The four counter cards in one row: the layout from 768px up, unchanged. */
const KPI_WIDE_COLUMNS = "repeat(4, 1fr)";

/**
 * Two cards per row below the shell's breakpoint (lib/layout.ts). Four in a
 * row at a 320px viewport leave each card 37px for its value, and a value such
 * as "0.020" in the cards' 22px monospace measured 55px wide, so it ran out of
 * its card (KPI.tsx leaves the choice of how many cards share a row to the
 * page). Two per row leave 112px (measured 2026-09-26). Each track is
 * NARROW_COLUMN, so the pair shares the row evenly whatever the labels say.
 */
const KPI_NARROW_COLUMNS = `repeat(2, ${NARROW_COLUMN})`;

/** Each chart's height from 768px up, as before. */
const CHART_HEIGHT_PX = 260;

export default function Benchmarks() {
  const narrow = useNarrowLayout();
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

      <div style={{ display: "grid", gridTemplateColumns: narrow ? KPI_NARROW_COLUMNS : KPI_WIDE_COLUMNS, gap: 12, marginBottom: 16 }}>
        <KPI label="Rounds accepted" value={accepted ?? "—"} />
        <KPI label="Rounds aborted" value={aborted ?? "—"} />
        <KPI label="Avg round ms" value={roundMsHist.length ? (roundMsHist.reduce((a, b) => a + b.ms!, 0) / roundMsHist.length).toFixed(0) : "—"} />
        <KPI label="Avg QBER" value={qberHist.length ? (qberHist.reduce((a, b) => a + b.qber!, 0) / qberHist.length).toFixed(3) : "—"} />
      </div>

      {/* useResizeHandler on both charts: Plotly reads its width from the
          page once, when it first draws, and the shell keeps this page
          mounted when the viewport crosses its breakpoint (a phone turned
          sideways, a window resized). Measured on 2026-09-26 without it:
          drawn at 1280px and resized to 375px, each chart stayed 996px wide
          in a 343px column and the page scrolled sideways. With it they
          follow the column (343px, and back to 996px). At a fixed viewport
          the first draw is the same as before. */}
      <Plot
        data={[
          { x: roundMsHist.map((r) => r.round), y: roundMsHist.map((r) => r.ms), type: "scatter", mode: "lines", name: "round ms", line: { color: "#5b8def" } },
        ]}
        layout={{
          ...common, height: CHART_HEIGHT_PX,
          title: { text: "BB84 round latency (ms)", font: { color: "#9aa9d8", size: 14 },
                   ...(narrow ? NARROW_TITLE : {}) },
          ...(narrow ? NARROW_TITLE_BAND : {}),
        }}
        style={{ width: "100%" }}
        useResizeHandler
        config={PLOT_CONFIG}
      />
      <Plot
        data={[
          { x: qberHist.map((r) => r.round), y: qberHist.map((r) => r.qber), type: "scatter", mode: "lines", name: "QBER", line: { color: "#ff5e7e" }, fill: "tozeroy" },
        ]}
        layout={{
          ...common, height: CHART_HEIGHT_PX, yaxis: { range: [0, 0.5], color: "#9aa9d8" },
          title: { text: "QBER history", font: { color: "#9aa9d8", size: 14 },
                   ...(narrow ? NARROW_TITLE : {}) },
          ...(narrow ? NARROW_TITLE_BAND : {}),
        }}
        style={{ width: "100%" }}
        useResizeHandler
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

/**
 * Below the shell's breakpoint the chart titles move out from under the
 * modebar.
 *
 * Plotly draws the modebar in each chart's top-right corner and centres the
 * title in the same band. Measured on 2026-09-26: the modebar is 192px wide and
 * runs from 2px to 25px below the chart's top edge at every width, and the
 * title from 2px to 18px. At a 320px viewport the chart is 288px wide and the
 * modebar starts 94px in, over the middle of "BB84 round latency (ms)"
 * (67-221px); at 375px it starts 149px in (title 94-249px). Left-aligning the
 * title would not clear it: the title is 154px and the modebar 192px, 346px
 * together, wider than the chart at either width. From 768px up the title and
 * margin are unchanged.
 *
 * So when narrow the title is anchored by its bottom to the top of the plot
 * area, and the top margin grows to hold it below the modebar. Measured with
 * these values at 320, 375, 414 and 600px: the title runs from 33px to 49px,
 * 8px clear of the modebar, and the plot area is 200px tall as it is from
 * 768px up.
 */
const NARROW_TOP_MARGIN_PX = 52;

/** Plotly's title.pad.b when narrow: keeps the title off the plot area's top edge. */
const NARROW_TITLE_PAD_PX = 6;

/** The title just above the plot area, below the modebar's band, when narrow. */
const NARROW_TITLE = { yref: "paper", y: 1, yanchor: "bottom", pad: { b: NARROW_TITLE_PAD_PX } };

/**
 * The taller top margin that holds the title when narrow. The chart grows by
 * the same amount so the plot area keeps the height it has from 768px up.
 */
const NARROW_TITLE_BAND = {
  margin: { ...common.margin, t: NARROW_TOP_MARGIN_PX },
  height: CHART_HEIGHT_PX + NARROW_TOP_MARGIN_PX - common.margin.t,
};
