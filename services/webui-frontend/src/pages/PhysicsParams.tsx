import { useEffect, useState } from "react";

/**
 * Physics parameter editor.
 *
 * config/qkd_params.yaml holds the *defaults*. The UI can OVERRIDE any editable
 * parameter at runtime (POST /api/sim/params); overrides are applied in-memory
 * on both KMEs and reset on restart — the YAML file is never modified. Press
 * "Optimize" to run a scikit-optimize Bayesian GP search for the best μ / ν.
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

const GROUPS: { title: string; prefix: string }[] = [
  { title: "Channel (fiber + detector)", prefix: "physical." },
  { title: "Source (WCP intensities)", prefix: "source." },
  { title: "Protocol", prefix: "protocol." },
  { title: "Simulator", prefix: "simulator." },
  { title: "Adversary (Eve)", prefix: "eve." },
];

const BACKENDS = ["qutip", "simqn", "sequence", "cvqkd", "tno", "composite_sim_to_net", "qkdnetsim_proxy"];

export default function PhysicsParams() {
  const [fields, setFields] = useState<EditableField[] | null>(null);
  const [backend, setBackend] = useState<string>("");
  const [edits, setEdits] = useState<Record<string, number | boolean>>({});
  const [opt, setOpt] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string>("");

  async function load() {
    try {
      const r = await fetch("/api/sim/params/editable");
      const j = await r.json();
      setFields(j.fields);
      const r2 = await fetch("/api/sim/params");
      const p = await r2.json();
      setBackend(p?.simulator?.backend ?? "");
    } catch { /* backend may be down */ }
  }
  useEffect(() => { load(); const t = setInterval(load, 5000); return () => clearInterval(t); }, []);

  function setEdit(path: string, v: number | boolean) {
    setEdits((e) => ({ ...e, [path]: v }));
  }

  async function applyEdits() {
    if (Object.keys(edits).length === 0) { setNote("No changes to apply."); return; }
    setBusy(true); setNote("");
    try {
      const r = await fetch("/api/sim/params", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ patch: edits }),
      });
      if (!r.ok) { setNote(`Apply failed: ${r.status} ${await r.text()}`); }
      else { setNote(`Applied ${Object.keys(edits).length} override(s).`); setEdits({}); }
    } finally { setBusy(false); await load(); }
  }

  async function resetParams() {
    setBusy(true); setNote("");
    try {
      await fetch("/api/sim/params/reset", { method: "POST" });
      setEdits({}); setNote("Reverted to config/qkd_params.yaml defaults.");
    } finally { setBusy(false); await load(); }
  }

  async function switchBackend(name: string) {
    setBusy(true);
    try { await fetch("/api/sim/backend", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name }) }); }
    finally { setBusy(false); await load(); }
  }

  async function runOptimize() {
    setBusy(true); setOpt(null);
    try {
      const r = await fetch("/api/sim/optimize", { method: "POST" });
      setOpt(await r.json());
    } finally { setBusy(false); }
  }

  if (!fields) return <div>Loading parameters…</div>;

  const dirty = Object.keys(edits).length;
  const anyOverridden = fields.some((f) => f.overridden);

  return (
    <div>
      <h2 style={{ marginTop: 0 }}>Physics Parameters</h2>
      <p style={{ color: "#9aa9d8", maxWidth: 760 }}>
        Defaults come from <code>config/qkd_params.yaml</code> (grounded in the
        openQKDsecurity precomputed table and the closed-form formulae in
        arXiv:2511.21253). <b>Edit any value below and press Apply</b> to override
        it at runtime on both KMEs — overrides are held in memory and reset on
        restart; the YAML file is never modified. Press <b>Reset</b> to revert to
        defaults, or <b>Optimize</b> for a Bayesian GP search of μ / ν.
      </p>

      {/* Apply / Reset toolbar */}
      <div style={{ display: "flex", gap: 10, alignItems: "center", margin: "12px 0",
                     flexWrap: "wrap" }}>
        <button onClick={applyEdits} disabled={busy || dirty === 0}
                style={{ ...primaryBtn, opacity: dirty === 0 ? 0.5 : 1 }}>
          {busy ? "Applying…" : `Apply${dirty ? ` (${dirty})` : ""}`}
        </button>
        <button onClick={resetParams} disabled={busy || !anyOverridden}
                style={{ ...resetBtn, opacity: anyOverridden ? 1 : 0.5 }}>
          Reset to defaults
        </button>
        {anyOverridden && (
          <span style={{ fontSize: 11, color: "#f5a623",
                          border: "1px solid #f5a62355", borderRadius: 10,
                          padding: "2px 10px" }}>
            ● runtime overrides active
          </span>
        )}
        {note && <span style={{ fontSize: 12, color: "#9aa9d8" }}>{note}</span>}
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
        {GROUPS.map((g) => {
          const groupFields = fields.filter((f) => f.path.startsWith(g.prefix));
          if (groupFields.length === 0) return null;
          return (
            <Panel key={g.prefix} title={g.title}>
              {groupFields.map((f) => (
                <FieldRow key={f.path} field={f}
                          draft={edits[f.path]}
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
            {BACKENDS.map((b) => (
              <button key={b} disabled={busy}
                      onClick={() => switchBackend(b)}
                      style={btn(b === backend)}>{b}</button>
            ))}
          </div>
        </Panel>
      </div>

      <div style={{ marginTop: 16 }}>
        <button onClick={runOptimize} disabled={busy} style={primaryBtn}>
          {busy ? "Optimizing…" : "Run Bayesian Optimization"}
        </button>
        {opt && (
          <pre style={preBox}>
{JSON.stringify(opt, null, 2)}
          </pre>
        )}
      </div>
    </div>
  );
}

function FieldRow({ field, draft, onChange }:
                  { field: EditableField; draft: number | boolean | undefined;
                    onChange: (v: number | boolean) => void }) {
  const label = LABELS[field.path] ?? field.path.split(".").pop()!;
  const dirty = draft !== undefined;
  const cur = dirty ? draft : field.value;
  return (
    <div style={{ display: "flex", justifyContent: "space-between",
                   alignItems: "center", padding: "4px 0", fontSize: 13, gap: 8 }}>
      <span style={{ color: "#9aa9d8" }}>
        {label}
        {field.overridden && (
          <span title="overridden at runtime"
                style={{ color: "#f5a623", marginLeft: 6 }}>●</span>
        )}
      </span>
      {field.type === "bool" ? (
        <input type="checkbox" checked={Boolean(cur)}
               onChange={(e) => onChange(e.target.checked)} />
      ) : (
        <input type="number" value={String(cur)}
               step="any"
               onChange={(e) => {
                 const n = field.type === "int"
                   ? parseInt(e.target.value, 10) : parseFloat(e.target.value);
                 if (!Number.isNaN(n)) onChange(n);
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
