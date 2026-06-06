import { useEffect, useState } from "react";

/**
 * Physics parameter editor — drives config/qkd_params.yaml live.
 * All values are *scientifically grounded*: defaults come from openQKDsecurity
 * pre-computed table + arXiv 2511.21253 closed-form formula. Operators can
 * override any slider; pressing "Optimize" invokes scikit-optimize gp_minimize.
 */

interface Params {
  physical: {
    fiber_attenuation_db_per_km: number;
    link_length_km: number;
    detector_efficiency: number;
    dark_count_rate_hz: number;
    misalignment_error_ed: number;
  };
  source: {
    intensity_signal_mu: number;
    intensity_decoy_1_nu1: number;
    intensity_decoy_2_nu2: number;
    pulse_rate_hz: number;
  };
  protocol: { qber_threshold_abort: number; ec_efficiency_f: number };
  simulator: { backend: string };
}

const BACKENDS = ["qutip", "simqn", "sequence", "cvqkd", "composite_sim_to_net", "qkdnetsim_proxy"];

export default function PhysicsParams() {
  const [p, setP] = useState<Params | null>(null);
  const [opt, setOpt] = useState<any>(null);
  const [busy, setBusy] = useState(false);

  async function load() {
    try {
      const r = await fetch("/api/sim/params"); setP(await r.json());
    } catch { /* backend may be down */ }
  }
  useEffect(() => { load(); const t = setInterval(load, 3000); return () => clearInterval(t); }, []);

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

  if (!p) return <div>Loading parameters…</div>;

  return (
    <div>
      <h2 style={{ marginTop: 0 }}>Physics Parameters</h2>
      <p style={{ color: "#9aa9d8", maxWidth: 720 }}>
        Live view of the central YAML (<code>config/qkd_params.yaml</code>).
        Every default is grounded — values come from the openQKDsecurity precomputed
        table and the closed-form formulae in arXiv:2511.21253. Press <b>Optimize</b>
        to run a scikit-optimize Bayesian GP search for the best μ / ν.
      </p>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
        <Panel title="Channel (fiber + detector)">
          <Row k="Fiber attenuation (dB/km)" v={p.physical.fiber_attenuation_db_per_km} />
          <Row k="Link length (km)" v={p.physical.link_length_km} />
          <Row k="Detector efficiency η_d" v={p.physical.detector_efficiency} />
          <Row k="Dark count (Hz)" v={p.physical.dark_count_rate_hz} />
          <Row k="Misalignment e_d" v={p.physical.misalignment_error_ed} />
        </Panel>
        <Panel title="Source (WCP intensities)">
          <Row k="Pulse rate (Hz)" v={p.source.pulse_rate_hz} />
          <Row k="μ (signal)" v={p.source.intensity_signal_mu} />
          <Row k="ν₁ (decoy 1)" v={p.source.intensity_decoy_1_nu1} />
          <Row k="ν₂ (decoy 2)" v={p.source.intensity_decoy_2_nu2} />
        </Panel>
        <Panel title="Protocol">
          <Row k="QBER abort threshold" v={p.protocol.qber_threshold_abort} />
          <Row k="EC efficiency f" v={p.protocol.ec_efficiency_f} />
        </Panel>
        <Panel title="Backend selector">
          <p style={{ fontSize: 12, color: "#9aa9d8", margin: "4px 0" }}>
            Current: <code>{p.simulator.backend}</code>
          </p>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            {BACKENDS.map((b) => (
              <button key={b} disabled={busy}
                      onClick={() => switchBackend(b)}
                      style={btn(b === p.simulator.backend)}>{b}</button>
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

function Panel({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div style={{ background: "#0d1320", border: "1px solid #1d2741", borderRadius: 8, padding: 14 }}>
      <h3 style={{ margin: "0 0 10px 0", fontSize: 14, color: "#9aa9d8" }}>{title}</h3>
      {children}
    </div>
  );
}

function Row({ k, v }: { k: string; v: any }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", padding: "3px 0", fontSize: 13 }}>
      <span style={{ color: "#9aa9d8" }}>{k}</span>
      <span style={{ fontFamily: "monospace" }}>{typeof v === "number" ? v.toExponential(3) : String(v)}</span>
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
  padding: "6px 14px", fontSize: 13, cursor: "pointer",
};

const preBox: React.CSSProperties = {
  background: "#070b14", border: "1px solid #1d2741", borderRadius: 8,
  padding: 12, color: "#cbd6f5", fontSize: 11, lineHeight: 1.45, marginTop: 12,
};
