import { useEffect, useState } from "react";
import Button from "../components/Button";
import {
  KEM_NAMES, SIG_NAMES, PQC_PROVIDER,
  kemRoundtrip, sigRoundtrip, SIG_FAMILY, kemInterop, type InteropResult,
  type KemName, type SigName, type KemResult, type SigResult,
} from "../lib/sim/pqc";

/**
 * PQC Validator.
 *
 * The round-trips run CLIENT-SIDE via @noble/post-quantum, so the public demo
 * needs no backend for this page. When the liboqs-backed pqc-validator service
 * IS reachable (the full local stack), the same algorithm is run there too and
 * the two are compared — an independent-implementation cross-check rather than
 * a single library marking its own homework.
 */
export default function PQCValidator() {
  const [kemName, setKemName] = useState<KemName>("ML-KEM-768");
  const [sigName, setSigName] = useState<SigName>("ML-DSA-65");
  const [kem, setKem] = useState<KemResult | null>(null);
  const [sig, setSig] = useState<SigResult | null>(null);
  const [server, setServer] = useState<any>(null);
  const [interop, setInterop] = useState<InteropResult | null>(null);
  const [serverAvailable, setServerAvailable] = useState<boolean | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Probe the optional server-side validator once. Its absence is a normal
  // state in the public demo, not an error.
  useEffect(() => {
    fetch("/api/pqc/algorithms")
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then(() => setServerAvailable(true))
      .catch(() => setServerAvailable(false));
  }, []);

  async function run() {
    setBusy(true);
    setError(null);
    try {
      // Yield first so the button's disabled state paints before the
      // synchronous crypto blocks the main thread.
      await new Promise((r) => setTimeout(r, 0));
      setKem(kemRoundtrip(kemName));
      setSig(sigRoundtrip(sigName));

      if (serverAvailable) {
        const r = await fetch("/api/pqc/roundtrip", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ algo: kemName }),
        });
        setServer(r.ok ? await r.json() : null);

        // The real cross-check: liboqs encapsulates to a key this browser
        // generated, and we decapsulate what comes back. Agreement here cannot
        // happen unless both implementations are correct.
        setInterop(await kemInterop(kemName));
      } else {
        setInterop(null);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  // Length agreement is kept only as a weak sanity line. It was previously the
  // WHOLE of the "independent cross-check": two implementations agreeing that
  // ML-KEM-768 ciphertext is 1088 bytes shows they read the same table in
  // FIPS 203, not that either computes ML-KEM correctly.
  const lengthsAgree =
    kem && server && typeof server.ss_len === "number"
      ? server.ss_len === kem.sharedSecretLen && server.ct_len === kem.cipherTextLen
      : null;

  return (
    <div>
      <h2 style={{ marginTop: 0 }}>PQC Validator</h2>
      <p style={{ color: "#9aa9d8", maxWidth: 760 }}>
        Runs NIST FIPS 203 (ML-KEM), FIPS 204 (ML-DSA) and FIPS 205 (SLH-DSA) round-trips
        <b> in your browser</b>. Each KEM round-trip encapsulates and
        decapsulates a shared secret and checks the two agree; each signature
        round-trip verifies a signature <i>and</i> confirms a tampered message
        is rejected.
      </p>

      <div style={{ display: "flex", gap: 12, alignItems: "center", margin: "14px 0", flexWrap: "wrap" }}>
        <label style={lbl}>KEM</label>
        <select value={kemName} onChange={(e) => setKemName(e.target.value as KemName)}
                disabled={busy} style={sel} aria-label="KEM algorithm">
          {KEM_NAMES.map((k) => <option key={k} value={k}>{k}</option>)}
        </select>

        <label style={lbl}>Signature</label>
        <select value={sigName} onChange={(e) => setSigName(e.target.value as SigName)}
                disabled={busy} style={sel} aria-label="Signature algorithm">
          {/* Family is shown in the option itself. Choosing a hash-based
              scheme is the whole point of the picker, and it also costs 1-2 s
              of main-thread work against ML-DSA's ~10 ms -- labelling it means
              the pause reads as the tradeoff it is, not as a hang. */}
          {SIG_NAMES.map((s) => (
            <option key={s} value={s}>{s} — {SIG_FAMILY[s]}</option>
          ))}
        </select>

        <Button onClick={run} disabled={busy} variant="primary">
          {busy ? "Running…" : "Run round-trips"}
        </Button>
      </div>

      {error && <div style={errBox}>✗ {error}</div>}

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
        <Panel title={`KEM — ${kemName}${kem ? ` (${kem.standard})` : ""}`}>
          {kem ? (
            <>
              <Row k="Shared secrets agree" v={<Verdict ok={kem.sharedSecretMatch} />} />
              <Row k="NIST category" v={String(kem.category)} />
              <Row k="Public key" v={`${kem.publicKeyLen} B`} />
              <Row k="Secret key" v={`${kem.secretKeyLen} B`} />
              <Row k="Ciphertext" v={`${kem.cipherTextLen} B`} />
              <Row k="Shared secret" v={`${kem.sharedSecretLen} B`} />
              <Row k="Elapsed" v={`${kem.elapsedMs.toFixed(1)} ms`} />
            </>
          ) : <Idle />}
        </Panel>

        {/* Standard comes from the result, not a literal. The heading said
            "FIPS 204" for every scheme, so SLH-DSA rendered with correct
            FIPS 205 sizes under a FIPS 204 title -- the same view-owns-a-
            duplicate-rule defect as the /e2e failure banner. */}
        <Panel title={`Signature — ${sigName}${sig ? ` (${sig.standard})` : ""}`}>
          {sig ? (
            <>
              <Row k="Signature verifies" v={<Verdict ok={sig.verified} />} />
              <Row k="Rejects tampered message" v={<Verdict ok={sig.rejectsTamperedMessage} />} />
              <Row k="NIST category" v={String(sig.category)} />
              <Row k="Public key" v={`${sig.publicKeyLen} B`} />
              <Row k="Secret key" v={`${sig.secretKeyLen} B`} />
              <Row k="Signature" v={`${sig.signatureLen} B`} />
              <Row k="Elapsed" v={`${sig.elapsedMs.toFixed(1)} ms`} />
            </>
          ) : <Idle />}
        </Panel>
      </div>

      <div style={{ marginTop: 16 }}>
        <Panel title="Independent cross-check — liboqs (server-side)">
          {serverAvailable === null ? <Idle /> : serverAvailable ? (
            server ? (
              <>
                <Row k="Shared secrets agree (liboqs encapsulated to this browser's key)"
                     v={interop === null ? "—" : <Verdict ok={interop.agrees} />} />
                {interop && (
                  <>
                    <Row k="Our SHA-256 (@noble)" v={<code>{interop.ourSha256.slice(0, 32)}…</code>} />
                    <Row k="Their SHA-256 (liboqs)" v={<code>{interop.theirSha256.slice(0, 32)}…</code>} />
                  </>
                )}
                <Row k="Lengths agree (weak: both read the same FIPS 203 table)"
                     v={lengthsAgree === null ? "—" : <Verdict ok={lengthsAgree} />} />
                <pre style={preBox}>{JSON.stringify(server, null, 2)}</pre>
              </>
            ) : <Idle />
          ) : (
            <p style={{ color: "#9aa9d8", fontSize: 12, margin: 0 }}>
              The liboqs validator service is not reachable, which is expected in
              the public demo — this page is fully client-side. Bring up the full
              stack (<code>make up</code>) to cross-check the browser results
              against liboqs.
            </p>
          )}
        </Panel>
      </div>

      <p style={{ color: "#6b7796", fontSize: 11, marginTop: 16, maxWidth: 760, lineHeight: 1.6 }}>
        In-browser primitives come from <code>{PQC_PROVIDER.name}</code>{" "}
        v{PQC_PROVIDER.version} ({PQC_PROVIDER.license}). Stated plainly: it is{" "}
        <b>self-audited</b>, not independently audited, and makes{" "}
        <b>no constant-time guarantee</b> — pure JavaScript cannot provide one.
        That is fine for a simulator with no real secrets. This project's actual
        key paths (arnika, Rosenpass, strongSwan) use native implementations.
      </p>
    </div>
  );
}

function Verdict({ ok }: { ok: boolean }) {
  return <span style={{ color: ok ? "#3ddc84" : "#e25555", fontWeight: 600 }}>{ok ? "✓ pass" : "✗ FAIL"}</span>;
}

function Idle() {
  return <div style={{ color: "#6b7796", fontSize: 12 }}>Press “Run round-trips”.</div>;
}

function Row({ k, v }: { k: string; v: React.ReactNode }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", padding: "3px 0", fontSize: 13 }}>
      <span style={{ color: "#9aa9d8" }}>{k}</span>
      <span style={{ fontFamily: "monospace" }}>{v}</span>
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

const lbl: React.CSSProperties = { fontSize: 13, color: "#9aa9d8" };
const sel: React.CSSProperties = {
  background: "#0d1320", color: "#fff", border: "1px solid #2a3760",
  borderRadius: 4, padding: "4px 8px", fontSize: 13,
};
const preBox: React.CSSProperties = {
  background: "#070b14", border: "1px solid #1d2741", borderRadius: 6,
  padding: 10, color: "#cbd6f5", fontSize: 11, lineHeight: 1.45, margin: "8px 0 0 0",
  overflowX: "auto",
};
const errBox: React.CSSProperties = {
  background: "#2a0f16", border: "1px solid #6b2230", borderRadius: 6,
  padding: 10, color: "#ffb3bd", fontSize: 12, margin: "0 0 12px 0",
};
