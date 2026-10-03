import { useEffect, useRef, useState, type ReactNode } from "react";
import PageHeader from "../components/PageHeader";
import ExportToolbar from "../components/ExportToolbar";
import KPI from "../components/KPI";
import Panel from "../components/Panel";
import Button from "../components/Button";
import MultiHopTopologySvg from "../components/MultiHopTopologySvg";
import PhaseSequenceSvg from "../components/PhaseSequenceSvg";
import PacketFlowTable from "../components/PacketFlowTable";
import FailureCascadeTimeline from "../components/FailureCascadeTimeline";
import { colors } from "../lib/commonStyles";
import { NARROW_COLUMN, narrowColumns, useNarrowLayout } from "../lib/layout";
import {
  DEFAULT_HOP_COUNT, MAX_HOP_COUNT, paperCsvRows, PaperSim, type PaperFlowState,
} from "../lib/sim/paperSim";

/**
 * KPI cards per row below the breakpoint in lib/layout.ts. The wide row puts
 * all five side by side. Measured on 2026-09-26 in headless Chrome: on a
 * 375px phone that left each card 59px, the labels broke inside words
 * ("packe / ts", "hands / hake"), and a five-character value such as 10.27
 * (55px) ran 9px past its card; at 320px, with a run in progress, the last
 * card's value ended at x=324 and pushed the page 4px wide. Two per row gives
 * a card 138px at 320px, a 112px content box: room for a label's longest word
 * and for an eight-digit value (88px in the KPI's 22px monospace). One per
 * row would also fit and would make the row five cards tall.
 */
const NARROW_KPI_COLUMNS = 2;
const NARROW_KPI_TEMPLATE = `repeat(${NARROW_KPI_COLUMNS}, ${NARROW_COLUMN})`;

/**
 * The grid-column of a card that takes a whole row of the narrow KPI grid.
 * Five cards in NARROW_KPI_COLUMNS = 2 leave the fifth alone on the last row,
 * where at its one track it filled half the row and left the other half
 * empty; spanning every track (1 to -1) gives it the row.
 */
const NARROW_FULL_ROW = "1 / -1";

/**
 * Below the breakpoint, puts `children` (one KPI card) in a grid item that
 * spans the whole row. From 768px up it renders the card on its own, so the
 * five-across row is the same markup as before the narrow layout existed.
 */
function FullRowWhenNarrow({ narrow, children }: { narrow: boolean; children: ReactNode }) {
  return narrow ? <div style={{ gridColumn: NARROW_FULL_ROW }}>{children}</div> : <>{children}</>;
}

/**
 * Paper Data Exchange page.
 *
 * Implements the multi-hop trusted-node Data Exchange described in
 * references/PQC-Enhanced_QKD_Networks_A_Layered_Approach.pdf (4.2 Integration
 * Workflow, 4.3 Fail-Safe Mechanism, Table 1) and matches the
 * arnika-project/arnika multi-hop image:
 *
 *   End Node Alice | Trusted Node | End Node Bob
 *
 * The paper numbers four stages, (1) quantum plane to (4) data tunnel. This
 * page runs five phases -- paperSim's PHASE_NAMES -- because stage (3) is split
 * into the WireGuard hop handshake and the Rosenpass handshake it carries, so
 * each of Table 1's rows is its own phase.
 *
 * The page is intentionally distinct from /e2e (single-tunnel concept) — it
 * shows the daisy chain, paper-quoted packet budgets, and the 240-720s
 * failure cascade. Round 5: Run/Pause/Reset drive a CLIENT-SIDE orchestrator
 * (src/lib/sim/paperSim.ts); no backend / no /ws/paper-flow.
 */

// PaperFlowState is imported from the simulator rather than re-declared here.
// The page previously carried its own copy of the interface, and the two drifted:
// the sim gained `engine` and the page's copy did not, so reading it failed to
// compile. One shape, one definition.
export default function PaperDataExchange() {
  const [state, setState] = useState<PaperFlowState | null>(null);
  const [hopCount, setHopCount] = useState(DEFAULT_HOP_COUNT);
  const simRef = useRef<PaperSim | null>(null);
  const narrow = useNarrowLayout();

  // Round 5: the multi-hop orchestration runs CLIENT-SIDE (no /ws/paper-flow).
  useEffect(() => {
    const sim = new PaperSim(setState);
    simRef.current = sim;
    return () => sim.dispose();
  }, []);

  /**
   * This run's log, from client state.
   *
   * Was logService="webui-backend", which downloaded the server's rotating log
   * -- a file containing nothing about a simulation that runs in the browser.
   */
  function runLog(): string {
    const s = state;
    if (!s) return "no run state\n";
    const head = [
      `# Paper Data Exchange run log`,
      `# generated:   ${new Date().toISOString()}`,
      `# engine:      ${s.engine ?? "client-side"}`,
      `# status:      ${s.status}`,
      `# hops:        ${s.hop_count}`,
      `# cycles:      ${s.cycles_total} (${s.cycles_succeeded} accepted)`,
      `# packets:     ${s.packets_total}  bytes: ${s.bytes_total}`,
      s.failure.active_layer
        ? `# failure:     ${s.failure.active_layer} (${s.failure.cascade.length}-stage cascade, `
          + `${s.failure.elapsed_s.toFixed(1)} s of cascade time run)`
        : "",
      // The header counters cover the whole run; the phase lines below do not.
      `# phases:      last ${s.history.length} of ${s.phases_total} shown`,
      "",
    ].filter(Boolean);
    const body = (s.history ?? []).map((h) => {
      const started = new Date(h.started_at * 1000).toISOString();
      const dur = h.completed_at
        ? `${Math.round((h.completed_at - h.started_at) * 1000)}ms` : "open";
      return `${started}  phase ${h.phase}  ${h.name}  (${dur})  ` +
             `pkts=${h.packets} bytes=${h.bytes}  ${JSON.stringify(h.detail)}`;
    });
    const cascade = (s.failure.cascade ?? []).map((c) =>
      `  +${c.t_offset_s}s  ${c.layer}: ${c.description}${c.fired ? "  [fired]" : ""}`);
    // What was done to the run: a cascade or a stalled cycle reads differently
    // once the reader can see the inject, pause or step that caused it.
    const actions = (s.operator_actions ?? []).map((a) =>
      `  ${new Date(a.at * 1000).toISOString()}  ${a.action}`);
    return [...head, ...body,
            ...(cascade.length ? ["", "# cascade schedule", ...cascade] : []),
            ...(actions.length
              ? ["", `# operator actions (last ${actions.length} of ${s.actions_total})`, ...actions]
              : []),
            ""].join("\n");
  }

  function ctl(action: "start" | "pause" | "resume" | "reset" | "step") {
    simRef.current?.[action]();
  }
  function configHopCount(n: number) {
    setHopCount(n);
    simRef.current?.setHopCount(n);
  }
  function injectFailure(layer: string) {
    simRef.current?.injectFailure(layer as any);
  }
  function clearFailure() {
    simRef.current?.clearFailure();
  }

  const status = state?.status ?? "idle";
  const phase = state?.current_phase ?? 0;
  const budgets = state?.paper_budgets.phases ?? [];
  const activeFailure = state?.failure.active_layer ?? null;

  return (
    <div>
      <PageHeader
        title="Paper Data Exchange (Spooren et al. arXiv:2604.05599, 4.2 Integration Workflow and 4.3 Fail-Safe Mechanism)"
        subtitle={
          <>
            Multi-hop trusted-node Data Exchange faithful to the
            arnika multi-hop diagram and the paper's Table 1 packet budgets
            ({/* Derived, not typed. This read "(9 packets / 5248 bytes per
                handshake)" as a literal while the two KPI cards thirty lines
                below rendered the same figure from
                `paper_budgets.total_handshake_*`. Editing a phase row would
                have moved the cards and left the sentence asserting the old
                total -- and the sentence is the one a reader quotes. */}
            {state?.paper_budgets.total_handshake_packets ?? "—"} packets /{" "}
            {state?.paper_budgets.total_handshake_bytes ?? "—"} bytes per
            handshake). Differs from
            <code> /e2e </code> (single-tunnel concept) by showing a daisy
            chain, the 5-phase swimlane and the 240-720 s failure cascade.
          </>
        }
      />

      {/* Export toolbar between explanation and figures, never overlapping */}
      <div style={{ marginBottom: 12 }}>
        <ExportToolbar
          name="paper-data-exchange"
          hasRunControl
          logProvider={runLog}
          pngTargetSelector="#paper-flow-topology-svg"
          jsonProvider={() => state ?? { status: "loading" }}
          csvProvider={() => paperCsvRows(state?.history ?? [])}
        />
      </div>

      {/*
        KPI cards. The last two were labelled "Live", which read as observed
        traffic sitting beside the paper's quoted constants. They are neither
        live nor independent of the "Paper bytes / handshake" card: PaperSim
        adds PHASE_BUDGETS[phase].bytes -- the paper's own Table 1 figures --
        into bytesTotal on every phase, so the byte total is 5248 (exactly what
        that card shows) times the number of completed cycles, plus the one
        quantity this page really produces: the ~64-byte ChaCha20-Poly1305
        record phase 5 seals. Named and footnoted as derived.
      */}
      <div style={{ display: "grid",
                     gridTemplateColumns: narrow ? NARROW_KPI_TEMPLATE : "repeat(5, 1fr)",
                     gap: 12, marginBottom: 16 }}>
        <KPI label="Paper packets / handshake"
             value={state?.paper_budgets.total_handshake_packets ?? "—"} />
        <KPI label="Paper bytes / handshake"
             value={state?.paper_budgets.total_handshake_bytes ?? "—"} />
        <KPI label="Mean setup @ 10 hops (s)"
             value={state?.paper_budgets.mean_10_hop_setup_s ?? "—"} />
        {/* `cycles_total` counts cycles STARTED -- paperSim.ts:240 increments it
            in beginCycle(), before any phase has run. `cycles_succeeded`
            counts the ones that finished without an injected failure. The
            label used to say "done", which is the second meaning while the
            value is the first. */}
        <KPI label="Sim cycles started (accepted)"
             value={`${state?.cycles_total ?? 0} (${state?.cycles_succeeded ?? 0})`} />
        {/* Was "Sim bytes (paper budget × cycles)". That label states an
            arithmetic relation the code does not maintain: bytes accrue per
            PHASE as each completes (paperSim.ts:297), so mid-cycle the total
            is not a multiple of 5248. Read live on the demo: the cards showed
            3 cycles and 10624 bytes, and 3 x 5248 = 15744. The 10624 is
            correct -- 2 completed cycles at 5248 plus their two ~64 B
            ChaCha20-Poly1305 records -- but a reader checking the stated
            multiplication finds it fails and cannot tell which number is
            wrong. Nothing could have caught it: both values were right, only
            the relation between them was invented. */}
        <FullRowWhenNarrow narrow={narrow}>
          <KPI label="Sim bytes accrued (per completed phase)"
               value={state?.bytes_total ?? 0} />
        </FullRowWhenNarrow>
      </div>
      <div style={{ fontSize: 11, color: colors.textSec, lineHeight: 1.5,
                     marginTop: -8, marginBottom: 16 }}>
        The two <b>Sim</b> cards are not measured traffic, and the byte total is
        not an independent check on the paper. This page has no network path: the
        orchestrator runs in the browser (<code>src/lib/sim/paperSim.ts</code>)
        and accrues each phase's byte budget straight from the paper's Table 1,
        so the total is those same constants summed over the phases that ran --
        5248 per completed cycle, the figure the <code>Paper bytes / handshake</code>
        card quotes. The only bytes this page itself produces are the ~64-byte
        ChaCha20-Poly1305 record phase 5 seals each cycle. Moving the
        trusted-node slider from 1 to {MAX_HOP_COUNT} changes the total by zero, because no
        per-hop traffic is being counted.
      </div>

      {/* Topology — primary image-2 faithful figure */}
      <Panel title="Multi-Hop Topology (image 2 faithful)">
        <MultiHopTopologySvg
          hopCount={state?.hop_count ?? hopCount}
          currentPhase={phase}
          failureLayer={state?.failure.active_layer ?? null}
          cascadeStages={state?.failure.cascade.length ?? 0}
          idle={status !== "running"}
        />
        <div style={{ display: "flex", gap: 10, alignItems: "center",
                       marginTop: 8, flexWrap: "wrap" }}>
          <span style={{ color: colors.textSec, fontSize: 12 }}>
            Trusted Nodes (hop count): {state?.hop_count ?? hopCount}
          </span>
          <input type="range" min={1} max={MAX_HOP_COUNT}
                 aria-label="Trusted node hop count"
                 value={state?.hop_count ?? hopCount}
                 onChange={(e) => configHopCount(parseInt(e.target.value, 10))}
                 style={{ flex: 1, maxWidth: 320 }} />
        </div>
      </Panel>

      {/* Run / Pause / Reset + failure injection */}
      <div style={{ display: "flex", gap: 8, margin: "12px 0", flexWrap: "wrap",
                     alignItems: "center" }}>
        <Button variant="success" onClick={() => ctl("start")}
                disabled={status === "running"}>▶ Run</Button>
        <Button variant="warn" onClick={() => ctl("pause")}
                disabled={status !== "running"}>⏸ Pause</Button>
        <Button variant="secondary" onClick={() => ctl("resume")}
                disabled={status !== "paused"}>▶ Resume</Button>
        <Button variant="danger" onClick={() => ctl("reset")}>⏹ Reset</Button>
        <Button variant="secondary" onClick={() => ctl("step")}
                disabled={status === "running"}
                title="Advance exactly one phase (only while stopped or paused)">⏭ Step</Button>
        <span style={{ width: 1, height: 18, background: colors.borderLt,
                        margin: "0 8px" }} />
        <span style={{ color: colors.textSec, fontSize: 12 }}>Inject failure:</span>
        {["qkd", "arnika", "wireguard", "rosenpass", "data"].map((layer) => {
          const isActive = activeFailure === layer;
          return (
            <Button key={layer}
                    variant={isActive ? "danger" : "ghost"} size="sm"
                    title={isActive
                      ? `Active: ${layer}-layer failure injected (drives the cascade below)`
                      : `Inject a ${layer}-layer failure`}
                    onClick={() => injectFailure(layer)}>
              {isActive ? `● ${layer}` : layer}
            </Button>
          );
        })}
        <Button variant={activeFailure ? "warn" : "ghost"} size="sm"
                disabled={!activeFailure}
                title="Clear the injected failure"
                onClick={clearFailure}>clear</Button>
        <span style={{ marginLeft: "auto", fontSize: 11, color: colors.textSec }}>
          {activeFailure && (
            <span style={{ color: colors.danger, fontWeight: 700, marginRight: 10 }}>
              ⚠ failure: {activeFailure}
            </span>
          )}
          status: <b style={{ color: colors.textPri }}>{status}</b> · phase:{" "}
          <b style={{ color: colors.danger }}>
            {phase || "idle"}
          </b>
        </span>
      </div>

      {/* Sequence diagram */}
      <Panel title="Sequence Diagram -- this page's 5 phases, splitting the paper's stages (1)-(4); budgets from Evaluation Test 1, Table 1">
        <PhaseSequenceSvg budgets={budgets} currentPhase={phase} />
      </Panel>

      {/* Packet flow + cascade. Side by side from 768px up; one column below
          it. Measured on 2026-09-26: at 375px the two columns were 164px
          each, and the packet table, 280px at its narrowest, ran out of its
          own panel and across the cascade panel beside it, while the cascade
          SVG shrank to 139px. */}
      <div style={{ display: "grid", gridTemplateColumns: narrowColumns(narrow, "1fr 1fr"),
                     gap: 16, marginTop: 16 }}>
        <PacketFlowTable budgets={budgets} currentPhase={phase} />
        <FailureCascadeTimeline
          status={status}
          activeLayer={state?.failure.active_layer ?? null}
          startedAt={state?.failure.started_at ?? null}
          elapsedS={state?.failure.elapsed_s ?? 0}
          events={state?.failure.cascade ?? []}
        />
      </div>

      {/* Latest data payload (phase 5 output) */}
      <Panel title="Latest Data Exchange Payload (phase 5 = paper stage (4), ChaCha20-Poly1305)">
        <pre style={{
          margin: 0, fontSize: 11, lineHeight: 1.4,
          color: colors.textPri, fontFamily: "monospace",
          wordBreak: "break-all", whiteSpace: "pre-wrap",
        }}>
{state?.last_data_payload_b64 || "(no payload yet — press Run)"}
        </pre>
      </Panel>
    </div>
  );
}
