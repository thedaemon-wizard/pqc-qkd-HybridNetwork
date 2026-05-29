import { useEffect, useState } from "react";

/**
 * Two-implementation cross-check page: same NIST PQC algorithm via liboqs
 * (production) and PQClean (reference) must produce identical results.
 * Currently exposes the liboqs side; PQClean side is invoked by tests/CI.
 */
export default function PQCValidator() {
  const [algos, setAlgos] = useState<any>(null);
  const [result, setResult] = useState<any>(null);
  const [algo, setAlgo] = useState("ML-KEM-768");
  const [busy, setBusy] = useState(false);

  async function load() {
    try {
      const r = await fetch("/api/pqc/algorithms"); setAlgos(await r.json());
    } catch { /* validator may be down */ }
  }
  useEffect(() => { load(); }, []);

  async function roundtrip() {
    setBusy(true);
    try {
      const r = await fetch("/api/pqc/roundtrip", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ algo }),
      });
      setResult(await r.json());
    } finally { setBusy(false); }
  }

  return (
    <div>
      <h2 style={{ marginTop: 0 }}>PQC Validator — liboqs vs PQClean</h2>
      <p style={{ color: "#9aa9d8", maxWidth: 720 }}>
        NIST FIPS 203/204/205 のすべてのアルゴリズムについて、production library
        (liboqs) と NIST reference impl (PQClean) で同一テストベクトルが同一結果になることを検証します。
      </p>

      {!algos ? <div>Loading…</div> : (
        <>
          <div style={{ display: "flex", gap: 8, alignItems: "center", margin: "12px 0" }}>
            <label style={{ fontSize: 13, color: "#9aa9d8" }}>Algorithm:</label>
            <select value={algo} onChange={(e) => setAlgo(e.target.value)}
                    style={{ background: "#0d1320", color: "#fff",
                             border: "1px solid #2a3760", borderRadius: 4, padding: "4px 8px" }}>
              {(algos.liboqs?.kems ?? []).map((k: string) => <option key={k} value={k}>{k}</option>)}
            </select>
            <button onClick={roundtrip} disabled={busy} style={primaryBtn}>
              {busy ? "Running…" : "Run roundtrip"}
            </button>
          </div>

          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
            <Panel title="liboqs (production)">
              <pre style={preBox}>{JSON.stringify(result, null, 2)}</pre>
            </Panel>
            <Panel title="PQClean (NIST reference)">
              <p style={{ color: "#9aa9d8", fontSize: 12 }}>
                {algos.pqclean?.available
                  ? `Mounted at ${algos.pqclean.path}; KAT test binaries built on demand.`
                  : "PQClean not mounted. Add submodule and rebuild."}
              </p>
            </Panel>
          </div>
        </>
      )}
    </div>
  );
}

function Panel({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div style={{ background: "#0d1320", border: "1px solid #1d2741", borderRadius: 8, padding: 14 }}>
      <h3 style={{ margin: "0 0 8px 0", fontSize: 14, color: "#9aa9d8" }}>{title}</h3>
      {children}
    </div>
  );
}

const primaryBtn: React.CSSProperties = {
  background: "#5b8def", color: "#fff", border: "none", borderRadius: 4,
  padding: "6px 14px", fontSize: 13, cursor: "pointer",
};

const preBox: React.CSSProperties = {
  background: "#070b14", border: "1px solid #1d2741", borderRadius: 6,
  padding: 10, color: "#cbd6f5", fontSize: 11, lineHeight: 1.45, margin: 0,
};
