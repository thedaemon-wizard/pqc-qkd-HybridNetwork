import { useEffect, useState } from "react";
import Button from "../components/Button";
import ExportToolbar from "../components/ExportToolbar";
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

  // Changing the picker discards the previous algorithm's result.
  //
  // Titling from `kem?.algo` stops the heading lying, but leaving a stale
  // result body under a picker set to something else is still a mismatch a
  // reader has to notice. Clearing makes the page say "press Run", which is
  // the truth. Same for the interop row, which is keyed to the KEM.
  useEffect(() => { setKem(null); setInterop(null); }, [kemName]);
  useEffect(() => { setSig(null); }, [sigName]);

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

      {/* Client-side results, so logProvider rather than logService: the
          server log describes nothing about a round-trip run in the browser. */}
      <div style={{ marginBottom: 12 }}>
        <ExportToolbar
          name="pqc-validator"
          logProvider={() => [
            "# PQC validator run",
            `# generated: ${new Date().toISOString()}`,
            `# library:   ${PQC_PROVIDER.name} ${PQC_PROVIDER.version} (${PQC_PROVIDER.license})`,
            `# audited:   ${PQC_PROVIDER.audited}   constant-time: ${PQC_PROVIDER.constantTime}`,
            "#",
            kem ? `KEM ${kem.algo} (${kem.standard}) cat=${kem.category} pk=${kem.publicKeyLen} `
                + `sk=${kem.secretKeyLen} ct=${kem.cipherTextLen} ss=${kem.sharedSecretLen} `
                + `match=${kem.sharedSecretMatch} ${kem.elapsedMs.toFixed(1)}ms` : "KEM (not run)",
            sig ? `SIG ${sig.algo} (${sig.standard}, ${sig.family}) cat=${sig.category} `
                + `pk=${sig.publicKeyLen} sk=${sig.secretKeyLen} sig=${sig.signatureLen} `
                + `verified=${sig.verified} rejects_tampered=${sig.rejectsTamperedMessage} `
                + `${sig.elapsedMs.toFixed(1)}ms` : "SIG (not run)",
            interop ? `INTEROP ${interop.algo} agrees=${interop.agrees} `
                + `ours=${interop.ourSha256} theirs=${interop.theirSha256} `
                + `via=${interop.serverImpl}` : "INTEROP (not run; needs the backend)",
          ].join("\n") + "\n"}
          jsonProvider={() => ({ provider: PQC_PROVIDER, kem, sig, interop, server })}
          csvProvider={() => [kem, sig].filter(Boolean).map((r: any) => ({
            algo: r.algo, standard: r.standard, family: r.family ?? "KEM",
            category: r.category, public_key_len: r.publicKeyLen,
            secret_key_len: r.secretKeyLen,
            ciphertext_or_signature_len: r.cipherTextLen ?? r.signatureLen,
            elapsed_ms: Number(r.elapsedMs.toFixed(2)),
          }))}
        />
      </div>
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
        {/* Titled from the RESULT, not the picker. `kemName` is the select
            state and `kem` is set only inside run(), so changing the
            dropdown without pressing Run left the heading naming one
            algorithm over another's category, key sizes and a green tick.
            The CSV export at :95 already used `kem.algo` and was right,
            so screen and export contradicted each other. */}
        <Panel title={`KEM — ${kem?.algo ?? kemName}${kem ? ` (${kem.standard})` : ""}`}>
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
        <Panel title={`Signature — ${sig?.algo ?? sigName}${sig ? ` (${sig.standard})` : ""}`}>
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
    // gap / flexShrink / minWidth are load-bearing. A bare `space-between` with
    // two auto-width spans does not overflow -- the value wraps -- but with no
    // minimum gap the label and value ABUT, and at a 700px content width /vpn
    // rendered `ProposalAES_GCM_16-256/PRF_HMAC_SHA2_384/...` as one unreadable
    // token. Measured in the browser on 2026-08-27; first collision at ~900px.
    // Four near-identical Row components exist (here, PQCValidator,
    // QuantumSecureE2E, and an UNUSED components/Row.tsx); all are fixed the
    // same way. Consolidating them is a separate change.
    <div style={{ display: "flex", justifyContent: "space-between",
                   gap: 12, padding: "3px 0", fontSize: 13 }}>
      <span style={{ color: "#9aa9d8", flexShrink: 0 }}>{k}</span>
      <span style={{ fontFamily: "monospace", minWidth: 0, textAlign: "right",
                     overflowWrap: "anywhere" }}>{v}</span>
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
