import { useState } from "react";

import { getStack } from "../api";
import { bundledEditableFields } from "../lib/sim/keyrate";
import { asymptoticSkrPerPulse, channelFromParams, qberEmu } from "../lib/sim/keyrate";
import { useLiveParamOverrides } from "../lib/useConfig";
import { usePoll } from "../lib/usePoll";
import ExportToolbar from "../components/ExportToolbar";
import FieldReferencePanel from "../components/FieldReferencePanel";

/**
 * Physics parameter editor.
 *
 * config/qkd_params.yaml holds the *defaults*. The UI can OVERRIDE any editable
 * parameter. The key-rate and the "Optimize" search are computed CLIENT-SIDE
 * (keyrate.ts, closed-form Lo-Ma), so an edit changes what this page shows
 * without any server involvement.
 *
 * Whether Apply ALSO reaches the KMEs depends on the host. The overrides are
 * process-global on both KMEs, which feed the live VPN lanes: on a shared host
 * one visitor's edit became every visitor's, last write winning. So the backend
 * accepts them only with ENABLE_LIVE_PARAM_OVERRIDES=true, reports that as
 * `live_param_overrides` in /api/config, and this page otherwise keeps Apply
 * and Reset in the browser and disables the backend switch -- saying so on
 * screen rather than sending a request it knows will be refused.
 */

interface EditableField {
  path: string;
  type: "float" | "int" | "bool";
  value: number | boolean;
  overridden: boolean;
}

const LABELS: Record<string, string> = {
  "physical.fiber_attenuation_db_per_km": "Fiber attenuation (dB/km)",
  "physical.link_length_km": "Link length (km)",
  "physical.detector_efficiency": "Detector efficiency η_d",
  "physical.dark_count_rate_hz": "Dark count rate (Hz)",
  "physical.misalignment_error_ed": "Misalignment e_d",
  "source.pulse_rate_hz": "Pulse rate (Hz)",
  "source.intensity_signal_mu": "μ (signal)",
  "source.intensity_decoy_1_nu1": "ν₁ (decoy 1)",
  "source.intensity_decoy_2_nu2": "ν₂ (decoy 2)",
  "source.basis_bias_pz": "Basis bias p_z",
  "protocol.ec_efficiency_f": "EC efficiency f",
  "protocol.qber_threshold_abort": "QBER abort threshold",
  "simulator.bb84_batch_size": "BB84 batch size",
  "eve.enabled": "Eve attack enabled",
  "eve.intercept_prob": "Eve intercept probability",
};

/**
 * Physical bounds per parameter. `[min, max]`; `null` means unbounded that side.
 *
 * Every numeric parameter on this page routed through one `<input type="number"
 * step="any">` with no `min` or `max`, so the page accepted values the physics
 * has no meaning for and then RENDERED THE RESULT: a negative link length gives
 * eta_total > 1 and a secret-key rate above one bit per pulse, displayed with
 * the same styling as a real figure.
 *
 * The server-side model gained its own guard (`_skr.py` rejects a basis bias
 * outside (0,1) and intensity probabilities that do not sum to 1), but a model
 * refusing to compute is the last line, not the first. The input should decline
 * the value before anything downstream has to decide what it means.
 *
 * These are bounds on MEANING, not on taste: a probability cannot exceed 1, an
 * error-correction efficiency cannot beat the Shannon limit (f >= 1), a
 * misalignment error above 1/2 is a relabelling of the bases.
 */
const BOUNDS: Record<string, [number | null, number | null]> = {
  "physical.link_length_km": [0, null],
  "physical.fiber_attenuation_db_per_km": [0, null],
  "physical.detector_efficiency": [0, 1],
  "physical.dark_count_rate_hz": [0, null],
  "physical.misalignment_error_ed": [0, 0.5],
  "source.pulse_rate_hz": [1, null],
  "source.intensity_signal_mu": [0, null],
  "source.intensity_decoy_1_nu1": [0, null],
  "source.intensity_decoy_2_nu2": [0, null],
  "source.basis_bias_pz": [0, 1],
  "protocol.ec_efficiency_f": [1, null],
  "protocol.qber_threshold_abort": [0, 0.5],
  "simulator.bb84_batch_size": [1, null],
  "eve.intercept_prob": [0, 1],
};

/** Parameters this page's own client-side panel actually reads. */
const CLIENT_SIDE_INPUTS = new Set([
  "physical.detector_efficiency", "physical.fiber_attenuation_db_per_km",
  "physical.link_length_km", "physical.dark_count_rate_hz",
  "physical.misalignment_error_ed", "source.pulse_rate_hz",
  "source.intensity_signal_mu", "source.intensity_decoy_1_nu1",
  "source.intensity_decoy_2_nu2", "protocol.ec_efficiency_f",
]);

const GROUPS: { title: string; prefix: string }[] = [
  { title: "Channel (fiber + detector)", prefix: "physical." },
  { title: "Source (WCP intensities)", prefix: "source." },
  { title: "Protocol", prefix: "protocol." },
  { title: "Simulator", prefix: "simulator." },
  { title: "Adversary (Eve)", prefix: "eve." },
];

const BACKENDS = ["qutip", "simqn", "sequence", "cvqkd", "tno", "composite_sim_to_net", "qkdnetsim_proxy"];

/**
 * Backends that forward to the `qkdnetsim-kme` container
 * (services/bb84-kme/app/backends/__init__.py: `composite_sim_to_net` wraps the
 * qkdnetsim proxy, `qkdnetsim_proxy` is it). That container exists only in the
 * `crossvalidate` compose overlay. Switching to either while it is not running
 * leaves every round failing, so the pool stops refilling on both KMEs -- the
 * buttons are offered only while `/api/stack` reports it running.
 */
const QKDNETSIM_DEPENDENT: ReadonlySet<string> = new Set(["composite_sim_to_net", "qkdnetsim_proxy"]);
const QKDNETSIM_SERVICE = "qkdnetsim-kme";

/** The page's wording when the host refuses live overrides; matches the backend's 403 detail. */
const LOCAL_ONLY_REASON =
  "live parameter overrides are disabled on this host (ENABLE_LIVE_PARAM_OVERRIDES=false); edits apply to the in-browser model only";

/** The Optimize button's grid: this page's own, named so the result can cite it. */
const OPT_GRID = { muFrom: 0.20, muTo: 0.90, nuFrom: 0.02, nuBelowMu: 0.01, step: 0.02 } as const;

/** Per-KME outcome of a fan-out POST, as `_fanout_result` in webui-backend reports it. */
interface FanoutNode { ok?: boolean; status?: number | null; error?: string }

/** A count from the backend, or a plain statement that it did not send one. */
const reported = (n: unknown): string => (typeof n === "number" ? String(n) : "(not reported)");

/**
 * Read a fan-out response and say which KMEs did NOT apply it, or null if all did.
 *
 * `sim_backend_proxy` answers HTTP 200 with `ok: false` when a KME refused or
 * could not be reached, so `r.ok` alone reported success that happened on
 * neither node. Every mutating action on this page goes through here.
 */
function fanoutFailure(r: Response, body: Record<string, unknown> | null): string | null {
  if (r.ok && body?.ok === true) return null;
  const nodes = (body?.nodes ?? {}) as Record<string, FanoutNode>;
  const failed = Object.entries(nodes)
    .filter(([, n]) => !n.ok)
    .map(([name, n]) => `${name} (${n.status != null ? `HTTP ${n.status}: ` : ""}${n.error ?? "no response"})`);
  if (failed.length) {
    return `reached ${reported(body?.reached)} of ${reported(body?.of)} KMEs; not applied on ${failed.join(", ")}`;
  }
  const detail = typeof body?.detail === "string" ? ` -- ${body.detail}` : "";
  return r.ok ? "not confirmed by the backend" : `HTTP ${r.status}${detail}`;
}

export default function PhysicsParams() {
  const [fields, setFields] = useState<EditableField[] | null>(null);
  const [backend, setBackend] = useState<string>("");
  const [edits, setEdits] = useState<Record<string, number | boolean>>({});
  /** Edits applied to the in-browser model when the host refuses live overrides. */
  const [localApplied, setLocalApplied] = useState<Record<string, number | boolean>>({});
  const [opt, setOpt] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string>("");
  /** `qkdnetsim-kme`'s status from /api/stack, or null when it could not be read. */
  const [qkdnetsim, setQkdnetsim] = useState<string | null>(null);
  const live = useLiveParamOverrides();
  /** True when `fields` came from BUNDLED_PARAMS rather than the running
   *  stack. Drives the banner; never inferred from the values themselves. */
  const [bundled, setBundled] = useState(false);

  async function load() {
    try {
      const r = await fetch("/api/sim/params/editable");
      const j = await r.json();
      if (!r.ok || !Array.isArray(j?.fields)) throw new Error(`HTTP ${r.status}`);
      setFields(j.fields);
      // Cleared HERE, as soon as live fields arrive. It was cleared only at the
      // end of the config-default branch below, and the stats branch returns
      // before reaching it -- so after one transient outage the "not observed"
      // banner stayed up over live values for the rest of the visit.
      setBundled(false);
      // Read the ACTUAL runtime backend (which `switch_backend` updates) from the
      // live stats — not the static config default in /api/sim/params, which the
      // runtime switch does not change (so the selector would never reflect it).
      try {
        const s = await fetch("/api/stats").then((x) => x.json());
        const rt = s?.alice?.backend ?? s?.bob?.backend;
        if (rt) { setBackend(rt); return; }
      } catch { /* stats unavailable → fall through to config default */ }
      const p = await fetch("/api/sim/params").then((x) => x.json());
      setBackend(p?.simulator?.backend ?? "");
      setBundled(false);
    } catch {
      // The backend is unreachable. This used to swallow the error and leave
      // `fields` null, so the render returned "Loading parameters..." FOREVER
      // -- "the backend is down" and "the request is in flight" were the same
      // pixels and the first state never left. Same defect /topology had, in a
      // page where the entire form sat behind it.
      //
      // Fall back to the bundled defaults so the form renders and the
      // client-side rate model -- which needs no backend at all -- still runs.
      // FLAGGED, not silently substituted: a value read from a running
      // deployment and a value compiled into the bundle are different claims,
      // and the banner says which is on screen.
      if (!fields) setFields(bundledEditableFields());
      setBundled(true);
    }
  }
  usePoll(load, 5000);

  // Separate poll, so a stack read that fails cannot hold up the form.
  async function loadStack() {
    try {
      const row = (await getStack()).find((s) => s.name === QKDNETSIM_SERVICE);
      setQkdnetsim(row?.status ?? "absent");
    } catch {
      setQkdnetsim(null);
    }
  }
  usePoll(loadStack, 5000);

  function setEdit(path: string, v: number | boolean) {
    setEdits((e) => ({ ...e, [path]: v }));
  }

  async function applyEdits() {
    const n = Object.keys(edits).length;
    if (n === 0) { setNote("No changes to apply."); return; }
    if (!live) {
      // Nothing is sent: the host refuses the route, and the KMEs are shared by
      // every visitor. The model on this page reads the same values either way.
      setLocalApplied((a) => ({ ...a, ...edits }));
      setEdits({});
      setNote(`Applied ${n} edit(s) to the in-browser model only; the KMEs were not changed.`);
      return;
    }
    setBusy(true); setNote("");
    try {
      const r = await fetch("/api/sim/params", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ patch: edits }),
      });
      const body = await r.json().catch(() => null);
      const failure = fanoutFailure(r, body);
      // Drafts are kept on a partial apply, so the user can see what did not
      // land and press Apply again.
      if (failure) setNote(`Apply not confirmed: ${failure}.`);
      else { setNote(`Applied ${n} override(s) on both KMEs.`); setEdits({}); }
    } catch (e) {
      setNote(`Apply failed: ${e instanceof Error ? e.message : e}.`);
    } finally { setBusy(false); await load(); }
  }

  async function resetParams() {
    if (!live) {
      setLocalApplied({}); setEdits({});
      setNote("Reverted the in-browser model to the values this page loaded; the KMEs were not changed.");
      return;
    }
    setBusy(true); setNote("");
    try {
      // The response is READ now. This was `await fetch(...)` with the result
      // discarded, and the backend returned {"ok": true} even when neither KME
      // was reachable -- so the note below asserted a revert that had happened
      // nowhere. Both halves are fixed; this half would still have lied if only
      // the backend had been.
      const r = await fetch("/api/sim/params/reset", { method: "POST" });
      const body = await r.json().catch(() => null);
      const failure = fanoutFailure(r, body);
      setEdits({});
      setNote(failure ? `Reset not confirmed: ${failure}.`
        : "Reverted to config/qkd_params.yaml defaults.");
    } catch (e) {
      setNote(`Reset failed: ${e instanceof Error ? e.message : e}.`);
    } finally { setBusy(false); await load(); }
  }

  async function switchBackend(name: string) {
    setBusy(true);
    try {
      // The response was discarded, so a refused switch (a 429 from the rate
      // limiter, a 4xx for an unknown backend, a KME that did not answer)
      // looked exactly like a successful one until the next poll quietly
      // failed to show the new name. `r.ok` alone was not enough either: the
      // fan-out answers 200 with `ok: false` when a KME refused.
      const r = await fetch("/api/sim/backend", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name }) });
      const body = await r.json().catch(() => null);
      const failure = fanoutFailure(r, body);
      setNote(failure ? `Backend switch to ${name} not applied: ${failure}.`
        : `Backend switched to ${name} on both KMEs.`);
    } catch (e) {
      setNote(`Backend switch to ${name} failed: ${e instanceof Error ? e.message : e}.`);
    } finally { setBusy(false); await load(); }
  }

  if (!fields) return <div>Loading parameters…</div>;

  // Live mode: drafts only (applied values come back in `fields`). Local mode:
  // drafts over what Apply kept in this browser. `localApplied` is ignored in
  // live mode, so edits applied before /api/config answered cannot sit on
  // screen looking like values the KMEs hold.
  const overlay = live ? {} : localApplied;
  const dirty = Object.keys(edits).length;
  const anyOverridden = live ? fields.some((f) => f.overridden) : Object.keys(overlay).length > 0;
  const canReset = live ? anyOverridden : anyOverridden || dirty > 0;

  // ---- Client-side key-rate (closed-form Lo-Ma; no backend) ----
  const current = (path: string): number | boolean | undefined =>
    edits[path] ?? overlay[path] ?? fields.find((f) => f.path === path)?.value;
  // A parameter the backend did not report is NOT zero. `?? 0` here turned an
  // absent detector efficiency into a link with no transmittance and rendered
  // the resulting rate as a real figure; now the derived panel says which
  // input is missing and computes nothing.
  const missingInputs = [...CLIENT_SIDE_INPUTS].filter((p) => current(p) === undefined);
  const pv = (path: string): number => Number(current(path));
  const model = missingInputs.length > 0 ? null : (() => {
    const { etaTotal, Y0 } = channelFromParams({
      detectorEfficiency: pv("physical.detector_efficiency"),
      fiberAttenuationDbPerKm: pv("physical.fiber_attenuation_db_per_km"),
      linkLengthKm: pv("physical.link_length_km"),
      darkCountRateHz: pv("physical.dark_count_rate_hz"),
      pulseRateHz: pv("source.pulse_rate_hz"),
    });
    const eD = pv("physical.misalignment_error_ed");
    const mu = pv("source.intensity_signal_mu");
    const nu1 = pv("source.intensity_decoy_1_nu1");
    const nu2 = pv("source.intensity_decoy_2_nu2");
    const fEC = pv("protocol.ec_efficiency_f");
    const pulseRateHz = pv("source.pulse_rate_hz");
    const skrPerPulse = asymptoticSkrPerPulse({ Y0, etaTotal, eD, mu, nu1, nu2, fEC });
    return {
      etaTotal, Y0, eD, mu, nu1, nu2, fEC, pulseRateHz, skrPerPulse,
      qber: qberEmu(Y0, etaTotal, eD, mu),
      skrBps: skrPerPulse * pulseRateHz,
    };
  })();

  // Client-side grid search over μ / ν₁ maximising the asymptotic SKR, over
  // OPT_GRID. That grid is this page's own and is not `optimizer.search_space`
  // in config/qkd_params.yaml (μ 0.30-0.90, ν₁ 0.05-0.20), which the removed
  // server optimiser used; the result names the grid it searched.
  function runOptimize() {
    if (!model) return;
    const { Y0, etaTotal, eD, nu2, fEC, pulseRateHz } = model;
    setBusy(true); setOpt(null);
    let best = { mu: model.mu, nu1: model.nu1, skr: model.skrPerPulse };
    for (let m = OPT_GRID.muFrom; m <= OPT_GRID.muTo; m += OPT_GRID.step) {
      for (let n = OPT_GRID.nuFrom; n < m - OPT_GRID.nuBelowMu; n += OPT_GRID.step) {
        const r = asymptoticSkrPerPulse({ Y0, etaTotal, eD, mu: m, nu1: n, nu2, fEC });
        if (r > best.skr) best = { mu: m, nu1: n, skr: r };
      }
    }
    setOpt({
      method: "client-side grid search (Lo-Ma closed form, asymptotic)",
      grid: `mu ${OPT_GRID.muFrom}-${OPT_GRID.muTo}, nu1 ${OPT_GRID.nuFrom} to mu-${OPT_GRID.nuBelowMu}, step ${OPT_GRID.step}; not optimizer.search_space`,
      mu: +best.mu.toFixed(3), nu1: +best.nu1.toFixed(3), nu2,
      skr_per_pulse: best.skr, skr_bps: best.skr * pulseRateHz,
    });
    setEdits((e) => ({
      ...e,
      "source.intensity_signal_mu": +best.mu.toFixed(3),
      "source.intensity_decoy_1_nu1": +best.nu1.toFixed(3),
    }));
    setBusy(false);
  }

  /**
   * The parameter set together with what it implies.
   *
   * Exporting the inputs alone would be half the evidence: the point of this
   * page is that a given channel yields a given rate, and a reader reproducing
   * the figure needs both sides. Every derived value here is computed
   * client-side from the same closed form the page displays, so the export and
   * the screen cannot disagree.
   */
  function snapshot() {
    // `fields` is non-null by the guard above, but TS cannot carry that
    // narrowing into a closure -- and asserting it with `!` would hide a real
    // null if the guard ever moves. An explicit empty set is honest: an export
    // taken before load simply has no parameters in it.
    const loaded = fields ?? [];
    const params: Record<string, number | boolean> = {};
    for (const f of loaded) params[f.path] = edits[f.path] ?? overlay[f.path] ?? f.value;
    return {
      generated_at: new Date().toISOString(),
      backend,
      // Where Apply puts an edit on this host: on both KMEs, or only in the
      // model this browser runs. The two are different claims about `parameters`.
      override_scope: live ? "kme" : "browser",
      overridden: live ? loaded.filter((f) => f.overridden).map((f) => f.path) : Object.keys(overlay),
      pending_edits: Object.keys(edits),
      parameters: params,
      derived: model ? {
        eta_total: model.etaTotal,
        Y0: model.Y0,
        qber: model.qber,
        skr_per_pulse: model.skrPerPulse,
        skr_bps: model.skrBps,
        model: "Lo-Ma two-decoy asymptotic, closed form (client-side)",
      } : null,
      not_computed_because_missing: missingInputs,
      optimizer: opt ?? null,
    };
  }

  const kpi = (v: number | undefined, fmt: (x: number) => string) =>
    v === undefined ? "—" : fmt(v);
  const qkdnetsimUp = qkdnetsim === "running";
  const qkdnetsimWhy = qkdnetsim === null
    ? `${QKDNETSIM_SERVICE}'s status could not be read from /api/stack`
    : `${QKDNETSIM_SERVICE} is ${qkdnetsim} on this host (it exists only in the crossvalidate compose overlay)`;

  return (
    <div>
      <h2 style={{ marginTop: 0 }}>Physics Parameters</h2>

      {bundled && (
        <p style={{ color: "#e0777d", fontSize: 12, margin: "0 0 12px" }}>
          Not observed &mdash; <code>GET /api/sim/params/editable</code> failed.
          The values below are the defaults compiled into this bundle from{" "}
          <code>config/qkd_params.yaml</code>, not the running stack's current
          configuration. The key-rate figures beneath them are still real: that
          model runs entirely in this browser.{" "}
          {live ? "Applying an edit to the KMEs needs the backend and will fail."
            : "Apply and Reset change only that in-browser model."}
        </p>
      )}

      {/* logProvider, not logService: the rate on this page is computed in the
          browser, so a server log would describe a different computation. */}
      <div style={{ marginBottom: 12 }}>
        <ExportToolbar
          name="physics-params"
          logProvider={() => {
            const s = snapshot();
            const lines = [
              "# Physics parameters and the rate they imply",
              `# generated: ${s.generated_at}`,
              `# backend:   ${s.backend || "(unknown)"}`,
              `# override scope: ${s.override_scope === "kme" ? "both KMEs (live)" : "this browser only"}`,
              `# overridden: ${s.overridden.length ? s.overridden.join(", ") : "(none)"}`,
              `# unapplied edits: ${s.pending_edits.length ? s.pending_edits.join(", ") : "(none)"}`,
              "#",
              "# parameter\tvalue",
            ];
            for (const [k, v] of Object.entries(s.parameters)) lines.push(`${k}\t${v}`);
            lines.push("#", "# derived (client-side, Lo-Ma two-decoy asymptotic)");
            if (s.derived) {
              lines.push(`eta_total\t${s.derived.eta_total}`);
              lines.push(`Y0\t${s.derived.Y0}`);
              lines.push(`qber\t${s.derived.qber}`);
              lines.push(`skr_per_pulse\t${s.derived.skr_per_pulse}`);
              lines.push(`skr_bps\t${s.derived.skr_bps}`);
            } else {
              lines.push(`# not computed: the backend did not report ${s.not_computed_because_missing.join(", ")}`);
            }
            return lines.join("\n") + "\n";
          }}
          jsonProvider={snapshot}
          csvProvider={() => (fields ?? []).map((f) => ({
            path: f.path,
            label: LABELS[f.path] ?? f.path,
            type: f.type,
            // `f.value` is not the config default: /sim/params/editable fills
            // it from config_loader.get(), which returns the YAML default
            // ALREADY overlaid with any applied runtime override. Exporting it
            // as `config_default` meant that after Apply the CSV presented the
            // overridden number as the shipped default.
            applied_value: f.value,
            effective: edits[f.path] ?? overlay[f.path] ?? f.value,
            // `edits` holds only UNAPPLIED drafts, and applyEdits() clears it
            // on success, so this column read false for exactly the parameters
            // whose override had actually taken effect. `f.overridden` is the
            // KME's own flag and survives Apply; the draft is its own column.
            overridden: f.overridden || f.path in edits || f.path in overlay,
            browser_only_override: f.path in overlay,
            pending_edit: f.path in edits,
          }))}
        />
      </div>
      <p style={{ color: "#9aa9d8", maxWidth: 760 }}>
        Defaults come from <code>config/qkd_params.yaml</code>, grounded in
        the precomputed table in <code>config/qkd_keyrate_table.json</code>.
        The key-rate panel below is the Lo&ndash;Ma two-decoy <b>asymptotic</b>{" "}
        bound (Lo&ndash;Ma&ndash;Chen, PRL 94, 230504); the KMEs and{" "}
        <code>/protocol-lab</code> use the finite-key rate of Lim et al.,
        PRA 89, 022307 (2014), which at the shipped block size and parameters is lower. <b>Edit any value below and press Apply</b> — the live
        key-rate recomputes <b>client-side</b> as you type.{" "}
        {live
          ? "Apply also syncs the values to both KMEs (in-memory; the YAML file is never modified; reset on restart), and Reset reverts them."
          : "On this host Apply and Reset change only the model in this browser: the KMEs are shared by every visitor and by the live VPN lanes, so the server does not accept overrides."}{" "}
        Press <b>Optimize</b> for a client-side μ / ν search (closed-form Lo-Ma).
      </p>

      {/* Apply / Reset toolbar */}
      <div style={{ display: "flex", gap: 10, alignItems: "center", margin: "12px 0",
                     flexWrap: "wrap" }}>
        <button onClick={applyEdits} disabled={busy || dirty === 0}
                style={dis(primaryBtn, busy || dirty === 0)}>
          {busy ? "Applying…" : `Apply${dirty ? ` (${dirty})` : ""}${live ? "" : " in this browser"}`}
        </button>
        <button onClick={resetParams} disabled={busy || !canReset}
                style={dis(resetBtn, busy || !canReset)}>
          {live ? "Reset to defaults" : "Reset this browser's edits"}
        </button>
        {anyOverridden && (
          <span style={{ fontSize: 11, color: "#f5a623",
                          border: "1px solid #f5a62355", borderRadius: 10,
                          padding: "2px 10px" }}>
            {live ? "● runtime overrides active on the KMEs" : "● in-browser edits active (not sent to the KMEs)"}
          </span>
        )}
        {note && <span style={{ fontSize: 12, color: "#9aa9d8" }}>{note}</span>}
      </div>
      {!live && (
        <p style={{ fontSize: 12, color: "#9aa9d8", margin: "0 0 12px" }}>
          Not sent to the server: {LOCAL_ONLY_REASON}.
        </p>
      )}

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
        {GROUPS.map((g) => {
          const groupFields = fields.filter((f) => f.path.startsWith(g.prefix));
          if (groupFields.length === 0) return null;
          return (
            <Panel key={g.prefix} title={g.title}>
              {groupFields.map((f) => (
                <FieldRow key={f.path} field={f}
                          draft={edits[f.path]}
                          browserValue={overlay[f.path]}
                          onChange={(v) => setEdit(f.path, v)} />
              ))}
            </Panel>
          );
        })}
        <Panel title="Backend selector (crypto-/sim-agility)">
          <p style={{ fontSize: 12, color: "#9aa9d8", margin: "4px 0" }}>
            Current: <code>{backend || "—"}</code>
          </p>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            {BACKENDS.map((b) => {
              const off = busy || !live || (QKDNETSIM_DEPENDENT.has(b) && !qkdnetsimUp);
              return (
                <button key={b} disabled={off}
                        title={!live ? LOCAL_ONLY_REASON
                          : QKDNETSIM_DEPENDENT.has(b) && !qkdnetsimUp ? qkdnetsimWhy : undefined}
                        onClick={() => switchBackend(b)}
                        style={dis(btn(b === backend), off)}>{b}</button>
              );
            })}
          </div>
          {!live && (
            <p style={{ fontSize: 11, color: "#f5a623", margin: "8px 0 0" }}>
              Switching is disabled: {LOCAL_ONLY_REASON}. The in-browser key-rate
              does not depend on the backend, so nothing on this page changes with it.
            </p>
          )}
          {!qkdnetsimUp && (
            <p style={{ fontSize: 11, color: "#6b7796", margin: "8px 0 0" }}>
              {[...QKDNETSIM_DEPENDENT].join(" and ")} {live ? "are disabled" : "would also stay disabled"}:{" "}
              {qkdnetsimWhy}, and both forward every round to it.
            </p>
          )}
          <p style={{ fontSize: 11, color: "#6b7796", marginBottom: 0, marginTop: 8 }}>
            Switches the bb84-kme physics backend used by the full-stack real KME
            (sim-agility); its effect is visible on the Benchmarks page. The
            client-side key-rate above is computed in-browser and is
            backend-independent.
          </p>
        </Panel>
      </div>

      {/* Live client-side key-rate (recomputes as you edit; closed-form Lo-Ma) */}
      <Panel title="Key-rate (client-side · closed-form Lo-Ma, asymptotic)">
        <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 12 }}>
          <KpiCell label="η_total (transmittance)" value={kpi(model?.etaTotal, (x) => x.toExponential(3))} />
          <KpiCell label="QBER E_μ" value={kpi(model?.qber, (x) => (x * 100).toFixed(2) + " %")} />
          <KpiCell label="SKR (bits/pulse)" value={kpi(model?.skrPerPulse, (x) => x.toExponential(3))} />
          <KpiCell label="SKR (bps)" value={kpi(model?.skrBps, (x) => x.toExponential(3))} />
        </div>
        {!model && (
          <p style={{ fontSize: 12, color: "#e0777d", margin: "8px 0 0" }}>
            Not computed: the backend did not report {missingInputs.join(", ")}.
          </p>
        )}
        <p style={{ fontSize: 11, color: "#6b7796", marginBottom: 0 }}>
          Computed in the browser — no backend call. From the{" "}
          <b>{CLIENT_SIDE_INPUTS.size} parameters this panel reads</b>, not all
          fifteen above: basis bias, QBER abort threshold, batch size and the
          two Eve fields do not enter these formulas and editing them will not
          move these numbers. They are not inert — the abort threshold gates the
          backend&apos;s accept decision and the Eve settings drive the
          simulator — but they act elsewhere, and a caption saying &quot;the
          current parameters&quot; implied all of them. Block size and the
          security parameters do not enter either: this is the Lo-Ma
          asymptotic bound, a different closed form from the finite-key rate
          the KMEs report and not that rate&apos;s large-block limit. With the
          shipped parameters it lies above the finite-key rate at the shipped
          block size; at much larger blocks the finite-key rate can exceed
          it near the QBER at which key stops.
          Edit a value above to see it update live.
        </p>
      </Panel>

      <FieldReferencePanel />

      <div style={{ marginTop: 16, display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
        <button onClick={runOptimize} disabled={busy || !model} style={dis(primaryBtn, busy || !model)}>
          {busy ? "Optimizing…" : "Optimize μ / ν (client-side)"}
        </button>
        <span style={{ fontSize: 11, color: "#3ddc84", border: "1px solid #1d4030",
                        borderRadius: 10, padding: "2px 10px" }}>
          ⚡ engine: client-side (keyrate.ts)
        </span>
        {opt && (
          <pre style={preBox}>
{JSON.stringify(opt, null, 2)}
          </pre>
        )}
      </div>
    </div>
  );
}

function KpiCell({ label, value }: { label: string; value: string }) {
  return (
    <div style={{ background: "#070b14", border: "1px solid #1d2741", borderRadius: 6, padding: "8px 10px" }}>
      <div style={{ fontSize: 10, color: "#6b7796" }}>{label}</div>
      <div style={{ fontSize: 15, color: "#d8e1ff", fontFamily: "monospace" }}>{value}</div>
    </div>
  );
}

function FieldRow({ field, draft, browserValue, onChange }:
                  { field: EditableField; draft: number | boolean | undefined;
                    /** A value Apply kept in this browser only (host refuses live overrides). */
                    browserValue: number | boolean | undefined;
                    onChange: (v: number | boolean) => void }) {
  const label = LABELS[field.path] ?? field.path.split(".").pop()!;
  const dirty = draft !== undefined;
  const cur = dirty ? draft : browserValue ?? field.value;
  return (
    <div style={{ display: "flex", justifyContent: "space-between",
                   alignItems: "center", padding: "4px 0", fontSize: 13, gap: 8 }}>
      <span style={{ color: "#9aa9d8" }}>
        {label}
        {field.overridden && (
          <span title="overridden at runtime on the KMEs"
                style={{ color: "#f5a623", marginLeft: 6 }}>●</span>
        )}
        {browserValue !== undefined && (
          <span title="edited in this browser only; not sent to the KMEs"
                style={{ color: "#5b8def", marginLeft: 6 }}>●</span>
        )}
      </span>
      {/* aria-label, not just adjacent text. The parameter name was rendered in
          a neighbouring <span> with no association to the control, so a screen
          reader announced fifteen bare "number" inputs with no indication of
          which physical quantity each one sets. */}
      {field.type === "bool" ? (
        <input type="checkbox" checked={Boolean(cur)}
               aria-label={label}
               onChange={(e) => onChange(e.target.checked)} />
      ) : (
        <input type="number" value={String(cur)}
               step="any"
               min={BOUNDS[field.path]?.[0] ?? undefined}
               max={BOUNDS[field.path]?.[1] ?? undefined}
               aria-label={label}
               onChange={(e) => {
                 const n = field.type === "int"
                   ? parseInt(e.target.value, 10) : parseFloat(e.target.value);
                 if (Number.isNaN(n)) return;
                 // `min`/`max` alone only style the field and block the
                 // spinner; a typed or pasted value still reaches onChange.
                 // Refuse it here so nothing downstream has to decide what a
                 // negative link length means.
                 const [lo, hi] = BOUNDS[field.path] ?? [null, null];
                 if (lo !== null && n < lo) return;
                 if (hi !== null && n > hi) return;
                 onChange(n);
               }}
               style={{
                 width: 120, textAlign: "right", fontFamily: "monospace",
                 fontSize: 12, padding: "3px 6px", borderRadius: 4,
                 background: "#070b14", color: dirty ? "#ffd479" : "#cbd6f5",
                 border: `1px solid ${dirty ? "#f5a623" : "#2a3760"}`,
               }} />
      )}
    </div>
  );
}

function Panel({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div style={{ background: "#0d1320", border: "1px solid #1d2741", borderRadius: 8, padding: 14 }}>
      <h3 style={{ margin: "0 0 10px 0", fontSize: 14, color: "#9aa9d8" }}>{title}</h3>
      {children}
    </div>
  );
}

const btn = (active: boolean): React.CSSProperties => ({
  background: active ? "#1a2440" : "#0d1320", color: active ? "#fff" : "#9aa9d8",
  border: "1px solid #2a3760", borderRadius: 4, padding: "4px 10px",
  fontSize: 11, cursor: "pointer",
});

// Make any inline button style disabled-aware: dim + not-allowed cursor.
const dis = (s: React.CSSProperties, disabled: boolean): React.CSSProperties =>
  disabled ? { ...s, opacity: 0.5, cursor: "not-allowed" } : s;

const primaryBtn: React.CSSProperties = {
  background: "#5b8def", color: "#fff", border: "none", borderRadius: 4,
  padding: "6px 14px", fontSize: 13, cursor: "pointer", fontWeight: 600,
};

const resetBtn: React.CSSProperties = {
  background: "#0d1320", color: "#e25555", border: "1px solid #e25555",
  borderRadius: 4, padding: "6px 14px", fontSize: 13, cursor: "pointer",
};

const preBox: React.CSSProperties = {
  background: "#070b14", border: "1px solid #1d2741", borderRadius: 8,
  padding: 12, color: "#cbd6f5", fontSize: 11, lineHeight: 1.45, marginTop: 12,
};
