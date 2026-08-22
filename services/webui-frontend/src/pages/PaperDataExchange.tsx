import { useEffect, useRef, useState } from "react";
import PageHeader from "../components/PageHeader";
import ExportToolbar from "../components/ExportToolbar";
import KPI from "../components/KPI";
import Panel from "../components/Panel";
import Button from "../components/Button";
import MultiHopTopologySvg from "../components/MultiHopTopologySvg";
import PhaseSequenceSvg, { type PhaseBudget } from "../components/PhaseSequenceSvg";
import PacketFlowTable from "../components/PacketFlowTable";
import FailureCascadeTimeline, { type CascadeEvent } from "../components/FailureCascadeTimeline";
import { colors } from "../lib/commonStyles";
import { NOMINAL_PHASE_DWELL_MS, PaperSim, type PaperFlowState } from "../lib/sim/paperSim";

/**
 * Paper Data Exchange page.
 *
 * Implements the multi-hop trusted-node Data Exchange described in
 * references/PQC-Enhanced_QKD_Networks_A_Layered_Approach.pdf and matches the
 * arnika-project/arnika multi-hop image (provided by the user) showing:
 *
 *   End Node Alice | Trusted Node | End Node Bob
 *      ① Quantum Plane  ② QKD Key IDs  ③ PQC Handshake  ④ Data Exchange
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
  const [hopCount, setHopCount] = useState(4);
  const simRef = useRef<PaperSim | null>(null);

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
      `# hops:        ${s.hop_count}  dual_path: ${s.dual_path}`,
      `# cycles:      ${s.cycles_total} (${s.cycles_succeeded} accepted)`,
      `# packets:     ${s.packets_total}  bytes: ${s.bytes_total}`,
      s.failure.active_layer
        ? `# failure:     ${s.failure.active_layer} (${s.failure.cascade.length}-stage cascade)`
        : "",
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
    return [...head, ...body,
            ...(cascade.length ? ["", "# cascade schedule", ...cascade] : []), ""].join("\n");
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
        title="Paper Data Exchange (Spooren et al. arXiv:2604.05599 §III)"
        subtitle={
          <>
            Multi-hop trusted-node Data Exchange faithful to the
            arnika multi-hop diagram and the paper's Table III packet budgets
            (9 packets / 5248 bytes per handshake). Differs from
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
          csvProvider={() => (state?.history ?? []).map((h) => ({
            phase: h.phase, name: h.name,
            started_at: new Date(h.started_at * 1000).toISOString(),
            completed_at: h.completed_at
              ? new Date(h.completed_at * 1000).toISOString() : "",
            // Wall-clock the UI sat on the phase, not a protocol timing: the
            // dwell is a fixed animation constant, and Chrome clamps timers to
            // ~1 Hz in a hidden tab. The nominal is exported beside it so a
            // reader can spot a throttled recording rather than plot it.
            ui_dwell_ms: h.completed_at
              ? Math.round((h.completed_at - h.started_at) * 1000) : "",
            nominal_dwell_ms: NOMINAL_PHASE_DWELL_MS,
            packets: h.packets, bytes: h.bytes,
          }))}
        />
      </div>

      {/* KPI cards (paper values + live) */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(5, 1fr)",
                     gap: 12, marginBottom: 16 }}>
        <KPI label="Paper packets / handshake"
             value={state?.paper_budgets.total_handshake_packets ?? "—"} />
        <KPI label="Paper bytes / handshake"
             value={state?.paper_budgets.total_handshake_bytes ?? "—"} />
        <KPI label="Mean setup @ 10 hops (s)"
             value={state?.paper_budgets.mean_10_hop_setup_s ?? "—"} />
        <KPI label="Live cycles done"
             value={state?.cycles_total ?? 0} />
        <KPI label="Live bytes total"
             value={state?.bytes_total ?? 0} />
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
          <input type="range" min={1} max={8}
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
      <Panel title="5-Phase Sequence Diagram (paper §IV-B Table III)">
        <PhaseSequenceSvg budgets={budgets} currentPhase={phase} />
      </Panel>

      {/* Packet flow + cascade */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr",
                     gap: 16, marginTop: 16 }}>
        <PacketFlowTable budgets={budgets} currentPhase={phase} />
        <FailureCascadeTimeline
          activeLayer={state?.failure.active_layer ?? null}
          startedAt={state?.failure.started_at ?? null}
          events={state?.failure.cascade ?? []}
        />
      </div>

      {/* Latest data payload (Phase 5 output) */}
      <Panel title="Latest Data Exchange Payload (Phase 5, ChaCha20-Poly1305)">
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
