import { useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import PageHeader from "../components/PageHeader";
import ExportToolbar from "../components/ExportToolbar";
import KPI from "../components/KPI";
import Panel from "../components/Panel";
import Button from "../components/Button";
import TopologyPresetSvg from "../components/TopologyPresetSvg";
import QBufferGauge from "../components/QBufferGauge";
import SBufferQueue from "../components/SBufferQueue";
import SDNControlPanel from "../components/SDNControlPanel";
import LoadPresetDropdown from "../components/LoadPresetDropdown";
import MessageTimeline from "../components/MessageTimeline";
import ScrollRegion from "../components/ScrollRegion";
import { colors } from "../lib/commonStyles";
import { formatRate, formatReported } from "../lib/formatRate";
import { narrowColumns, useNarrowLayout } from "../lib/layout";
import {
  DEFAULT_PRESET_ID, presetById, quantityValue, scenarioById,
  type FailureTarget, type Quantity,
} from "../lib/sim/protocolLab/publishedNetworks";
import { MODEL_LABEL, modelRateFor } from "../lib/sim/protocolLab/rates";
import {
  ProtocolLabSim, protocolLabCsvRows, type ProtocolLabState,
} from "../lib/sim/protocolLabSim";

/**
 * Protocol Lab: trusted-node key relay, re-routing and the ETSI GS QKD 014 /
 * 004 interfaces, simulated in the browser over five published QKD networks.
 *
 * Everything on this page is SIMULATED from published numbers; nothing is read
 * from the running stack, and the page makes no request of its own (exports
 * excepted, as on every page). The banner says so before anything runs.
 */

/**
 * The narrowest the "Links as published" table is laid out below the shell's
 * breakpoint, in CSS px; its own box scrolls sideways past that. The table
 * has width: 100%, so in a phone's panel (263px at 320px, 318px at 375px) the
 * auto layout gave every column its min-content width and the Length and model
 * columns became about 45px wide, one word per line: the tallest SECOQC row
 * was 432px and Thuringia's 500px (measured 2026-09-26 at 375px). At 800px the
 * tallest row of any preset is 194px. From 768px up the table is laid out as
 * before, so this applies only when narrow.
 */
const NARROW_LINKS_TABLE_MIN_PX = 800;

/**
 * Below the breakpoint, the Q-buffer gauges' rows (a link id and its rate)
 * may break a word anywhere. overflow-wrap is inherited, so this reaches the
 * rate text inside QBufferGauge. Today's values have spaces and fit, but an
 * unbroken one is not caught by anything else: measured on 2026-09-26,
 * seventy-five "x" characters put in place of each rate ran to x = 476px,
 * 185px past its row at a 320px viewport and 130px at 375px (the rate is not
 * monospace, so other characters end elsewhere). "anywhere", not
 * "break-word", because only "anywhere" lowers the text's min-content width,
 * which is what lets the flex item shrink to the row. From 768px up the
 * gauges are as before.
 */
const NARROW_GAUGE_TEXT: CSSProperties = { overflowWrap: "anywhere" };

export default function ProtocolLab() {
  const narrow = useNarrowLayout();
  const [state, setState] = useState<ProtocolLabState | null>(null);
  const [target, setTarget] = useState<string>("");
  const [rate, setRate] = useState<string>("1");
  const simRef = useRef<ProtocolLabSim | null>(null);

  useEffect(() => {
    const sim = new ProtocolLabSim(setState, { presetId: DEFAULT_PRESET_ID });
    simRef.current = sim;
    return () => sim.dispose();
  }, []);

  const preset = presetById(state?.preset_id ?? DEFAULT_PRESET_ID);
  const scenario = state?.scenario_id ? scenarioById(state.scenario_id) : null;
  const status = state?.status ?? "idle";

  const scaleBits = useMemo(() => {
    if (!scenario || scenario.accounting !== "stores") return null;
    return Math.max(...Object.values(scenario.stores).map((q) => quantityValue(q)));
  }, [scenario]);

  function ctl(action: "start" | "pause" | "resume" | "reset" | "step") {
    simRef.current?.[action]();
  }
  function load(presetId: string, scenarioId: string | null) {
    setTarget("");
    simRef.current?.loadPreset(presetId, scenarioId);
  }
  function applyDemand(from: string, to: string, r: string) {
    setRate(r);
    simRef.current?.setDemand(from, to, Number(r));
  }
  function inject() {
    if (!target) return;
    const [kind, id] = target.split(":");
    const t: FailureTarget = kind === "node" ? { kind: "node", id } : { kind: "link", id, reason: "outage" };
    simRef.current?.injectFailure(t);
  }

  function runLog(): string {
    const s = state;
    if (!s) return "no run state\n";
    const head = [
      "# Protocol Lab run log (simulation; nothing here is observed from the running stack)",
      `# generated:  ${new Date().toISOString()}`,
      `# engine:     ${s.engine}; ${s.spec}`,
      `# network:    ${preset.meta.citation} (${preset.meta.licence})`,
      `# scenario:   ${scenario ? scenario.title : "free play"}`,
      `# accounting: ${s.accounting}`,
      `# demand:     ${s.demand.from} -> ${s.demand.to}, ${s.demand.label} (${s.demand.source})`,
      `# policy:     ${s.policy}`,
      `# seed:       ${s.seed_pinned ? s.seed : "unpinned"}`,
      "",
    ];
    const body = s.reroutes.map((r) => `t=${r.t_s}s  ${r.to ? r.to.join(">") : "no route"}  (${r.reason})`);
    const msgs = s.messages.map((m) => `t=${m.t_s}s  [${m.lane}] ${m.text}${m.transition ? ` [${m.transition}]` : ""}`);
    return [...head, "# route changes", ...body, "", "# last messages", ...msgs, ""].join("\n");
  }

  const delivered = state && state.sim_time_s > 0 ? state.delivered_bits / state.sim_time_s : null;
  const shown = formatRate(delivered);
  const cell = { padding: "3px 8px", borderBottom: `1px solid ${colors.border}`, verticalAlign: "top" as const };
  const q = (v: Quantity | null) => (v ? formatReported(v) : "not reported");

  return (
    <div>
      <PageHeader
        title="Protocol Lab (trusted-node relay over published QKD networks)"
        subtitle={<>Key relay, re-routing and the ETSI GS QKD 014 / 004 application
          interfaces, simulated over five published networks. Compare the running
          stack on <code>/e2e</code> and the multi-hop phases on <code>/paper-flow</code>.</>}
      />

      <div role="note" style={{ border: `1px solid ${colors.warn}`, background: colors.panelDark,
                                 color: colors.textPri, borderRadius: 8, padding: "10px 12px",
                                 fontSize: 13, marginBottom: 12, lineHeight: 1.5 }}>
        <b>Simulation.</b> Everything here is computed in your browser from published
        measurements; nothing is observed from the running stack. The running stack keys
        each WireGuard hop independently from its own ETSI GS QKD 014 KME pair and
        implements no trusted-node key relay and no re-routing. Its KME can serve ETSI GS
        QKD 004 V2.1.1 over this project's own HTTP binding, but that endpoint is switched
        off on this demo. No qkdnetsim binary is run.
      </div>

      <div style={{ marginBottom: 12 }}>
        <ExportToolbar
          name="protocol-lab"
          hasRunControl
          logProvider={runLog}
          pngTargetSelector="#protocol-lab-topology-svg"
          jsonProvider={() => state ? { network: preset.meta, scenario, ...state } : { status: "loading" }}
          csvProvider={() => state ? protocolLabCsvRows(state) : []}
        />
      </div>

      <Panel title="Network and scenario" style={{ marginBottom: 12 }}>
        <LoadPresetDropdown presetId={preset.meta.id} scenarioId={state?.scenario_id ?? null} onChange={load} />
        {state && !scenario && state.accounting === "keys" && (
          <div style={{ display: "flex", gap: 12, flexWrap: "wrap", alignItems: "center", marginTop: 8, fontSize: 12, color: colors.textSec }}>
            <label>From{" "}
              <select aria-label="Demand from" value={state.demand.from}
                      onChange={(e) => applyDemand(e.target.value, state.demand.to, rate)}>
                {preset.nodes.map((n) => <option key={n.id} value={n.id}>{n.label}</option>)}
              </select>
            </label>
            <label>To{" "}
              <select aria-label="Demand to" value={state.demand.to}
                      onChange={(e) => applyDemand(state.demand.from, e.target.value, rate)}>
                {preset.nodes.map((n) => <option key={n.id} value={n.id}>{n.label}</option>)}
              </select>
            </label>
            <label>Key requests per second{" "}
              <input aria-label="Key requests per second" type="number" min={0} step={0.1} value={rate}
                     style={{ width: 70 }}
                     onChange={(e) => applyDemand(state.demand.from, state.demand.to, e.target.value)} />
            </label>
            <span style={{ color: colors.textMute }}>set on this page; not from the source</span>
          </div>
        )}
        <div style={{ fontSize: 12, color: colors.textSec, marginTop: 8 }}>
          <b>Counting:</b> {state?.accounting ?? "..."} -- {state?.accounting_why}
        </div>
      </Panel>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))", gap: 12, marginBottom: 12 }}>
        <KPI label={`Delivered, simulated (${shown.unit})`} value={shown.value} />
        <KPI label="Route hops (relays)" value={state?.route ? `${state.route.hops} (${state.route.relays})` : "none"} />
        <KPI label="Simulated time (s)" value={state?.sim_time_s ?? 0} />
        <KPI label="Route changes" value={state ? Math.max(0, state.reroutes.length - 1) : 0} />
        <KPI label="Requests ok / failed" value={!state ? "--"
          : state.requests_ok === null ? `not counted (${state.accounting} accounting)`
          : `${state.requests_ok} / ${state.requests_failed}`} />
      </div>

      <Panel title={`Topology: ${preset.meta.title} (this project's layout, not the source's figure)`} style={{ marginBottom: 12 }}>
        {state && <TopologyPresetSvg preset={preset} links={state.links} route={state.route} downNodes={state.down_nodes} />}
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center", marginTop: 8 }}>
          <Button onClick={() => ctl("start")} disabled={status === "running"}>▶ Run</Button>
          <Button variant="secondary" onClick={() => ctl("pause")} disabled={status !== "running"}>⏸ Pause</Button>
          <Button variant="secondary" onClick={() => ctl("resume")} disabled={status !== "paused"}>▶ Resume</Button>
          <Button variant="secondary" onClick={() => ctl("step")} disabled={status === "running"}>⏭ Step</Button>
          <Button variant="ghost" onClick={() => ctl("reset")}>⏹ Reset</Button>
          <span style={{ fontSize: 12, color: colors.textSec }}>status: <b>{status}</b>; tick {state?.tick ?? 0} = {state?.tick_s ?? 0} s each</span>
        </div>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center", marginTop: 8 }}>
          <select aria-label="Failure target" value={target} onChange={(e) => setTarget(e.target.value)}>
            <option value="">choose a link or node</option>
            {preset.links.filter((l) => l.kind === "qkd").map((l) => <option key={l.id} value={`link:${l.id}`}>link {l.id}</option>)}
            {preset.nodes.map((n) => <option key={n.id} value={`node:${n.id}`}>node {n.label}</option>)}
          </select>
          <Button variant="danger" size="sm" onClick={inject} disabled={!target}>Inject failure</Button>
          <Button variant="warn" size="sm" onClick={() => simRef.current?.injectRandomFailure()}>Random link outage</Button>
          <Button variant="ghost" size="sm" onClick={() => simRef.current?.clearFailure()}>Clear failures</Button>
          {scenario?.events.map((ev) => (
            <Button key={ev.id} size="sm" variant={ev.action === "fail" ? "danger" : "success"} title={ev.ref}
                    onClick={() => ev.action === "fail" ? simRef.current?.injectFailure(ev.target) : simRef.current?.clearFailure(ev.target)}>
              {ev.label}
            </Button>
          ))}
        </div>
        {state?.seed_pinned && <div style={{ fontSize: 11, color: colors.textMute, marginTop: 4 }}>Random outages pinned by ?seed={state.seed}</div>}
      </Panel>

      {/* The 300px minimum is wider than a 320px phone's content box (288px
          after the 16px gutters), so the one column auto-fit made there was
          12px wider than <main> and every store panel ran into the right
          gutter. Below the breakpoint it is one shrinkable column; from 768px
          up the template is unchanged. */}
      <div style={{ display: "grid", gridTemplateColumns: narrowColumns(narrow, "repeat(auto-fit, minmax(300px, 1fr))"), gap: 12, marginBottom: 12 }}>
        <Panel title="Link key stores (Q-buffers)">
          <div style={narrow ? NARROW_GAUGE_TEXT : undefined}>
            {state?.links.filter((l) => l.kind === "qkd").map((l) => (
              <QBufferGauge key={l.id} link={l} accounting={state.accounting} keyBits={state.key_bits} scaleBits={scaleBits} />
            ))}
          </div>
        </Panel>
        <Panel title="Service-side store (S-buffer)">
          {state && <SBufferQueue state={state} />}
          {state?.last_relay && (
            <div style={{ fontSize: 11, color: colors.textMute, marginTop: 8, fontFamily: "monospace" }}>
              Last relay: key {state.last_relay.key_prefix}... over {state.last_relay.hops} hop(s), pads{" "}
              {state.last_relay.pad_prefixes.map((p) => `${p}...`).join(" ")}; recovered equals sent:{" "}
              {String(state.last_relay.recovered_equals_sent)} (prefixes only; zeroed on reset)
            </div>
          )}
        </Panel>
        <Panel title="Route controller (simulation, display only)">
          {state && <SDNControlPanel state={state} />}
        </Panel>
      </div>

      <Panel title="Messages" style={{ marginBottom: 12 }}>
        {state && <MessageTimeline messages={state.messages} />}
      </Panel>

      <Panel title="Links as published" style={{ marginBottom: 12 }}>
        <ScrollRegion aria-label="Links as published table">
          <table style={{ borderCollapse: "collapse", fontSize: 12, color: colors.textSec, width: "100%",
                          minWidth: narrow ? NARROW_LINKS_TABLE_MIN_PX : undefined }}>
            <thead>
              <tr>{["Link", "System", "Length", "Loss", "Rate (reported)", "QBER (reported)", "Rate (model, this project)", "Notes"].map((h) =>
                <th key={h} style={{ ...cell, textAlign: "left", color: colors.textPri }}>{h}</th>)}</tr>
            </thead>
            <tbody>
              {preset.links.map((l) => {
                const m = modelRateFor(l);
                const mr = m.bps === null ? null : formatRate(m.bps);
                return (
                  <tr key={l.id}>
                    <td style={cell}><code>{l.id}</code></td>
                    <td style={cell}>{l.system ?? "--"} ({l.protocol})</td>
                    <td style={cell}>{q(l.length)}{l.lengthAlt.length ? <><br /><span style={{ color: colors.textMute }}>also {l.lengthAlt.map((a) => `${formatReported(a)} (${a.ref})`).join("; ")}</span></> : null}</td>
                    <td style={cell}>{q(l.loss)}</td>
                    <td style={cell} title={l.rate?.ref}>{q(l.rate)}</td>
                    <td style={cell} title={l.qber?.ref}>{q(l.qber)}</td>
                    <td style={cell}>{mr ? `${mr.value} ${mr.unit} at ${m.bps !== null ? m.lossShown : ""}` : <span style={{ color: colors.textMute }}>{m.bps === null ? m.why : ""}</span>}</td>
                    <td style={cell}>{l.notes.join(" ")}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </ScrollRegion>
        <div style={{ fontSize: 11, color: colors.textMute, marginTop: 6 }}>
          Reported values keep the source's digits and qualifiers; hover a value for its reference.
          The model column is {MODEL_LABEL}. It is not a prediction for the vendor's system and never drives the simulation.
          {" "}{preset.notes.join(" ")}
        </div>
      </Panel>

      {scenario && (
        <Panel title="What the source reports, and the limits of this replay">
          <div style={{ fontSize: 12, color: colors.textSec, lineHeight: 1.6 }}>
            <div>{scenario.published.note} ({scenario.published.ref})</div>
            <ul style={{ margin: "6px 0 0 0", paddingLeft: 18 }}>
              {scenario.limits.map((x, i) => <li key={i}>{x}</li>)}
            </ul>
          </div>
        </Panel>
      )}
    </div>
  );
}
