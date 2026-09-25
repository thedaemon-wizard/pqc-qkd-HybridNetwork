import { useEffect, useState } from "react";

import { assumptionOf, crossCheckAgility, type CrossCheckResult } from "../lib/sim/agilityCrossCheck";

import { describeVerdict } from "./crosscheckVerdict";
import PageHeader from "../components/PageHeader";
import ExportToolbar from "../components/ExportToolbar";
import Panel from "../components/Panel";
import KPI from "../components/KPI";
import Button from "../components/Button";
import { colors } from "../lib/commonStyles";

/**
 * Implementation Verification page.
 *
 * Aggregates three independent "research-implementation verification" checks:
 *  1. Crypto-agility matrix — ML-KEM (encap/decap), ML-DSA and SLH-DSA
 *     (sign, verify, reject a tampered message) via liboqs, cross-checked
 *     in the browser against @noble. A PQClean column used to sit here
 *     reporting test-binary presence; it was always "—" because the binaries
 *     are never built, so it advertised a comparison that never ran.
 *  2. Key-rate cross-check — our closed-form Lo-Ma rate vs the independent
 *     TNO-Quantum qkd_key_rate engine (Apache-2.0) at the current config.
 *  3. Paper packet-budget match — arXiv:2604.05599 Table 1 handshake budgets.
 */

interface AgilityRow {
  algo: string; family: string; enabled: boolean; ok: boolean;
  pk_len?: number; ct_len?: number; ss_len?: number; sig_len?: number;
  /** SIG rows: a tampered message was verified and rejected. */
  rejects_tampered?: boolean;
  assumption?: string;
  error?: string;
}

/**
 * The liboqs verdict for one row. A signature passes only if the genuine
 * message verified AND the tampered one was rejected; `ok` alone was
 * `verify(...)`, which a verify that accepts everything also passes.
 */
function liboqsVerdict(r: AgilityRow): { text: string; pass: boolean } {
  if (!r.enabled) return { text: "n/a", pass: false };
  if (r.family !== "SIG") return r.ok ? { text: "PASS ✓", pass: true } : { text: "FAIL ✗", pass: false };
  if (!r.ok) return { text: "FAIL ✗ (verify)", pass: false };
  if (r.rejects_tampered === true) return { text: "PASS ✓ (verify + rejects tampered)", pass: true };
  if (r.rejects_tampered === false) return { text: "FAIL ✗ (accepted a tampered message)", pass: false };
  return { text: "verify ✓ · tamper check not reported", pass: false };
}

export default function Verification() {
  const [agility, setAgility] = useState<any>(null);
  // Cross-check, not replacement. Wiring agilityMatrix() in as a SUBSTITUTE
  // would falsify the panel heading, which names liboqs; running both keeps
  // the heading true and adds a second, independent implementation.
  const [cross, setCross] = useState<CrossCheckResult | null>(null);
  const [crossBusy, setCrossBusy] = useState(false);

  /** Deliberately NOT run on mount. Measured at 5.9 s on a desktop -- the four
   *  SLH-DSA parameter sets dominate it, and checklist row 4.6.11 records
   *  SLH-DSA-SHA2-192s alone at ~2.2 s in-browser. Running that synchronously
   *  when the page loads freezes the tab, and on a phone it is far worse. So
   *  it is an explicit action with the cost on the button, which is also how
   *  /pqc handles its own round-trips. */
  async function runCross() {
    setCrossBusy(true);
    // Yield first so the button's disabled state paints before the main
    // thread is taken; without this the UI shows nothing until it finishes.
    // (The cost is the browser running its four SLH-DSA sets, SHA2 128s, 128f,
    // 192s and 256s; the liboqs matrix runs the same four server-side.)
    await new Promise((r) => setTimeout(r, 0));
    try {
      setCross(crossCheckAgility(agility?.matrix ?? null));
    } finally { setCrossBusy(false); }
  }
  const [keyrate, setKeyrate] = useState<any>(null);
  const [budgets, setBudgets] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string>("");
  // Why each panel has no data, when it has none. A 429 from the rate limiter
  // or a 503 from pqc-validator used to be stored AS the data -- its JSON body
  // `{"detail": ...}` -- and panel 1 then called `.map` on a matrix that was
  // not there, which blanked the whole app.
  const [failed, setFailed] = useState<{ agility?: string; keyrate?: string; budgets?: string }>({});

  async function getJson(url: string, init?: RequestInit): Promise<any> {
    const r = await fetch(url, init);
    const body = await r.json().catch(() => null);
    if (!r.ok) throw new Error(`HTTP ${r.status}${body?.detail ? `: ${body.detail}` : ""}`);
    return body;
  }

  async function runAll() {
    setBusy(true); setErr(""); setFailed({});
    try {
      const [a, k, b] = await Promise.allSettled([
        getJson("/api/pqc/agility", { method: "POST" }),
        getJson("/api/verify/keyrate"),
        getJson("/api/verify/paper-budgets"),
      ]);
      const why = (x: PromiseRejectedResult) => (x.reason instanceof Error ? x.reason.message : String(x.reason));
      const f: typeof failed = {};
      if (a.status === "fulfilled" && Array.isArray(a.value?.matrix)) setAgility(a.value);
      else f.agility = a.status === "rejected" ? why(a) : "response carried no matrix";
      if (k.status === "fulfilled") setKeyrate(k.value); else f.keyrate = why(k);
      if (b.status === "fulfilled") setBudgets(b.value); else f.budgets = why(b);
      setFailed(f);
      if (f.agility && f.keyrate && f.budgets) setErr("Backend services unavailable.");
    } finally { setBusy(false); }
  }

  useEffect(() => { runAll(); }, []);

  const fmt = (x: number | null | undefined, d = 3) =>
    typeof x === "number" ? x.toExponential(d) : "—";

  /** Render an absent export field as an em dash. A bare `${x}` writes the
   *  literal string "undefined" into a file this page offers as citable
   *  evidence, where it reads as a value rather than as a missing one. */
  const cite = (x: unknown) => (x === undefined || x === null ? "—" : String(x));

  return (
    <div>
      <PageHeader
        title="Implementation Verification"
        subtitle={
          <>Independent evidence that this PoC matches the research it implements:
            crypto-agility across NIST PQC algorithms (liboqs), a key-rate
            cross-check against the independent <b>TNO-Quantum</b> engine, and the
            paper packet budgets from <code>arXiv:2604.05599</code>.</>
        }
      />

      {/* Below the header, as on every other page. This page is headed
          "Implementation Verification" and had no way to
          export the verification. Whoever needs the evidence -- a reviewer, a
          paper appendix -- had to screenshot a table. The whole point of the
          page is producing something citable. */}
      <div style={{ marginBottom: 12 }}>
        <ExportToolbar
          name="verification"
          animated={false}
          logProvider={() => {
            const lines = [
              "# Implementation verification evidence",
              `# generated: ${new Date().toISOString()}`,
              "#",
              "# Crypto-agility matrix (liboqs)",
            ];
            const rows = agility?.matrix ?? [];
            for (const r of rows) {
              lines.push(`${r.algo}\t${r.family}\t${r.enabled ? "enabled" : "disabled"}`
                + `\t${liboqsVerdict(r).text}`
                + (r.pk_len ? `\tpk=${r.pk_len}` : "")
                + (r.ct_len ? ` ct=${r.ct_len}` : "")
                + (r.ss_len ? ` ss=${r.ss_len}` : "")
                + (r.sig_len ? ` sig=${r.sig_len}` : ""));
            }
            if (keyrate) {
              lines.push("#", "# Key-rate cross-check");
              lines.push(`distance_km\t${keyrate.distance_km}`);
              lines.push(`ours_bps\t${keyrate.ours_closed_form?.skr_bps}`);
              lines.push(`tno_bps\t${keyrate.tno?.skr_bps}`);
              // `verdict`, not `same_order_of_magnitude`. The old line wrote
              // `false` into the citable export for five different outcomes,
              // one of which was the two implementations agreeing completely.
              lines.push(`verdict\t${keyrate.verdict}`);
              lines.push(`relative_delta\t${keyrate.relative_delta ?? "n/a (no ratio defined)"}`);
            }
            if (budgets) {
              // `/api/verify/paper-budgets` returns computed_total_* and
              // paper_total_*. It does NOT return total_handshake_*: that is the
              // shape of `paper_budgets.as_dict()`, which the endpoint wraps and
              // renames -- its docstring says exactly this. Reading the unwrapped
              // names put "total_packets<TAB>undefined" in the export while the
              // panel beside it rendered 9 and 5248 from that same response, and
              // the export is the only artefact a reviewer can cite.
              // "paper_total_*" is the SUM of Table 1's three rows, computed
              // by the backend; the paper prints no total.
              lines.push("#", "# Paper budgets (arXiv:2604.05599 Table 1; paper_total_* = sum of its rows)");
              lines.push(`computed_total_packets\t${cite(budgets.computed_total_packets)}`);
              lines.push(`paper_total_packets\t${cite(budgets.paper_total_packets)}`);
              lines.push(`computed_total_bytes\t${cite(budgets.computed_total_bytes)}`);
              lines.push(`paper_total_bytes\t${cite(budgets.paper_total_bytes)}`);
              lines.push(`packets_match\t${cite(budgets.packets_match)}`);
              lines.push(`bytes_match\t${cite(budgets.bytes_match)}`);
            }
            return lines.join("\n") + "\n";
          }}
          jsonProvider={() => ({ agility, keyrate, budgets })}
          csvProvider={() => (agility?.matrix ?? []).map((r: any) => ({
            algo: r.algo, family: r.family, enabled: r.enabled, ok: r.ok,
            // null, not false, for a KEM row or a validator that does not
            // report it: absent is "not checked", not "failed".
            rejects_tampered: typeof r.rejects_tampered === "boolean" ? r.rejects_tampered : null,
            assumption: r.assumption ?? assumptionOf(r.algo),
            pk_len: r.pk_len ?? null, ct_len: r.ct_len ?? null,
            ss_len: r.ss_len ?? null, sig_len: r.sig_len ?? null,
          }))}
        />
      </div>

      <div style={{ margin: "12px 0" }}>
        <Button variant="primary" onClick={runAll} disabled={busy}>
          {busy ? "Running…" : "Re-run all checks"}
        </Button>
        {err && <span style={{ marginLeft: 12, color: colors.danger, fontSize: 12 }}>{err}</span>}
      </div>

      {/* 1. Crypto-agility matrix */}
      {/* SLH-DSA belongs in the title: pqc-validator ships six signature
          algorithms (main.py DEFAULT_SIG_ALGOS), three of them SLH-DSA,
          so the matrix is nine rows and the panel rendered three families
          under a heading naming two. */}
      <Panel title="1 · Crypto-Agility Matrix (liboqs — ML-KEM, HQC, ML-DSA, SLH-DSA)">
        {!agility ? (failed.agility ? <NotObserved why={failed.agility} /> : <Loading />) : (
          <>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)",
                           gap: 12, marginBottom: 12 }}>
              <KPI label="Algorithms exercised" value={agility.summary?.total ?? "—"} />
              <KPI label="Passed" value={agility.summary?.passed ?? "—"} />
              <KPI label="All pass"
                   value={agility.summary?.all_pass ? "YES ✓" : "no"} />
            </div>
            <table style={{ width: "100%", fontSize: 12, color: colors.textPri,
                             borderCollapse: "collapse" }}>
              <thead>
                <tr style={{ color: colors.textMute, textAlign: "left" }}>
                  <th style={th}>Algorithm</th><th style={th}>Family</th>
                  <th style={th}>Hardness assumption</th>
                  <th style={th}>liboqs</th><th style={th}>sizes (B)</th>
                </tr>
              </thead>
              <tbody>
                {(agility.matrix as AgilityRow[]).map((r) => {
                  const v = liboqsVerdict(r);
                  return (
                  <tr key={r.algo} style={{ borderTop: `1px solid ${colors.border}` }}>
                    <td style={td}>{r.algo}</td>
                    <td style={td}>{r.family}</td>
                    <td style={td}>{r.assumption ?? assumptionOf(r.algo) ?? "not recorded"}</td>
                    <td style={{ ...td, color: v.pass ? colors.success : r.enabled ? colors.warn : colors.textMute,
                                  fontWeight: 700 }}>
                      {v.text}
                    </td>
                    <td style={{ ...td, fontFamily: "monospace" }}>
                      {r.family === "KEM"
                        ? `pk ${r.pk_len ?? "–"} · ct ${r.ct_len ?? "–"} · ss ${r.ss_len ?? "–"}`
                        : `pk ${r.pk_len ?? "–"} · sig ${r.sig_len ?? "–"}`}
                    </td>
                  </tr>
                  );
                })}
              </tbody>
            </table>
            <p style={{ fontSize: 11, color: colors.textMute, marginTop: 8 }}>
              This matrix shows that one interface runs every listed parameter
              set — KEMs ML-KEM 512/768/1024 and HQC-1/3/5, signatures ML-DSA
              44/65/87 and SLH-DSA-SHA2 128s/128f/192s/256s. HQC is code-based
              and SLH-DSA hash-based rather than lattice-based (the assumption
              column), which is the point: the interface does not care what the
              hardness assumption is. That is
              agility of this test harness; the system-level agility is the
              environment-driven IKE proposal on <code>/vpn</code>.
            </p>
          </>
        )}

        <div style={{ marginTop: 14, borderTop: `1px solid ${colors.borderLt}`,
                      paddingTop: 10 }}>
          <button onClick={runCross} disabled={crossBusy}
                  style={{ fontSize: 12 }}>
            {crossBusy
              ? "Running the matrix in this browser..."
              : "Cross-check against @noble in this browser (~6 s)"}
          </button>
          {!cross && !crossBusy && (
            <p style={{ fontSize: 11, color: colors.textMute, marginTop: 6 }}>
              Not run automatically: the four SLH-DSA parameter sets take
              seconds each in pure JavaScript, and doing that on page load
              would freeze the tab.
            </p>
          )}
        </div>

        {cross && cross.compared.length > 0 && (
          <div style={{ marginTop: 14, borderTop: `1px solid ${colors.borderLt}`,
                        paddingTop: 10 }}>
            <b style={{ fontSize: 12 }}>
              Independent cross-check &mdash; the same matrix in your browser
              (@noble)
            </b>
            {/* A <table>: Row renders a <tr>, which this block placed straight
                inside a <div> -- invalid nesting, and a broken layout. */}
            <table style={{ width: "100%", fontSize: 12, color: colors.textPri }}>
              <tbody>
                <Row k="Algorithms both implementations ran"
                     v={`${cross.compared.length}`} />
                <Row k="Round-trip passes in BOTH (strong)"
                     v={cross.allBothPass ? "yes" : "no"}
                     ok={cross.allBothPass} />
                <Row k="Byte lengths agree (weak — both read the same FIPS table)"
                     v={cross.allLengthsAgree ? "yes" : "no"}
                     ok={cross.allLengthsAgree} />
                {cross.serverTamperNotReported.length > 0 && (
                  <Row k="liboqs signatures with no tampered-message check reported"
                       v={cross.serverTamperNotReported.join(", ")} ok={false} />
                )}
                {cross.serverOnly.length > 0 && (
                  <Row k="liboqs only, not exercised in-browser"
                       v={cross.serverOnly.join(", ")} />
                )}
                {cross.clientOnly.length > 0 && (
                  <Row k="In-browser only, not in the liboqs matrix"
                       v={cross.clientOnly.join(", ")} />
                )}
                {cross.compared.flatMap((c) => c.lengthNotes).map((n, i) => (
                  <Row key={i} k="Length mismatch" v={n} ok={false} />
                ))}
              </tbody>
            </table>
            <p style={{ fontSize: 11, color: colors.textMute, marginTop: 8 }}>
              Two independently written implementations exercising the same
              algorithm set. What is strong here is that both ran a real
              round-trip and both passed &mdash; for signatures that means, on
              both sides, verifying a good signature <i>and</i> rejecting a
              tampered one; a liboqs row that does not report its tampered-message
              check (<code>rejects_tampered</code>) is not counted as a pass.
              What is weak is length agreement: both read the same FIPS
              203/204/205 parameter tables, so a wrong implementation produces
              the right sizes too. The conclusive test &mdash; liboqs
              encapsulating to a key this browser generated, and the two shared
              secrets agreeing &mdash; runs on <code>/pqc</code>.
            </p>
          </div>
        )}
      </Panel>

      {/* 2. Key-rate cross-check */}
      <Panel title="2 · Key-Rate Cross-Check (our closed form vs TNO-Quantum)">
        {!keyrate ? (failed.keyrate ? <NotObserved why={failed.keyrate} /> : <Loading />) : keyrate.error && !keyrate.tno ? (
          <p style={{ color: colors.warn, fontSize: 12 }}>
            TNO engine unavailable: {keyrate.error}
          </p>
        ) : (
          <>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)",
                           gap: 12, marginBottom: 12 }}>
              <KPI label="Distance (km)" value={keyrate.distance_km ?? "—"} />
              {/* `?? 0` ahead of `.toFixed` made the trailing `?? "—"` dead
                  code: the value was always a number, so a MISSING attenuation
                  rendered as a confident "0.0" dB instead of as no reading.
                  The sibling KPI above already does this correctly. */}
              <KPI label="Attenuation (dB)"
                   value={keyrate.attenuation_db?.toFixed(1) ?? "—"} />
              <KPI label="Ours (bits/pulse)"
                   value={fmt(keyrate.ours_closed_form?.rate_per_pulse)} />
              <KPI label="TNO (bits/pulse)"
                   value={fmt(keyrate.tno?.rate_per_pulse)} />
            </div>
            <table style={{ width: "100%", fontSize: 12, color: colors.textPri }}>
              <tbody>
                <Row k="Our method" v={keyrate.ours_closed_form?.method} />
                <Row k="TNO protocol" v={keyrate.tno?.protocol ?? "—"} />
                <Row k="TNO optimal μ" v={keyrate.tno?.mu_opt?.toFixed?.(3) ?? "—"} />
                <Row k="Relative Δ"
                     v={keyrate.relative_delta != null
                        ? `${(keyrate.relative_delta * 100).toFixed(1)} %` : "—"} />
                <Row k="Cross-check"
                     v={describeVerdict(keyrate.verdict).label}
                     ok={describeVerdict(keyrate.verdict).ok} />
              </tbody>
            </table>
            <p style={{ fontSize: 11, color: colors.textMute, marginTop: 8 }}>
              {/* The wording is derived from the verdict, not asserted. This
                  paragraph used to state that the two implementations "agree to
                  order of magnitude" unconditionally, so it kept claiming
                  agreement in the same render where the row beside it said
                  "review". */}
              Our closed-form Lo-Ma bound against TNO-Quantum's optimiser:{" "}
              {describeVerdict(keyrate.verdict).detail} Source:{" "}
              {keyrate.tno?.source ?? "—"}.
            </p>
          </>
        )}
      </Panel>

      {/* 3. Paper packet-budget match */}
      <Panel title="3 · Paper Packet-Budget Match (arXiv:2604.05599 Table 1)">
        {!budgets ? (failed.budgets ? <NotObserved why={failed.budgets} /> : <Loading />) : (
          <>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)",
                           gap: 12, marginBottom: 12 }}>
              <KPI label="Computed packets" value={budgets.computed_total_packets ?? "—"} />
              <KPI label="Table 1 rows, summed (packets)" value={budgets.paper_total_packets ?? "—"} />
              <KPI label="Computed bytes" value={budgets.computed_total_bytes ?? "—"} />
              <KPI label="Table 1 rows, summed (bytes)" value={budgets.paper_total_bytes ?? "—"} />
            </div>
            <table style={{ width: "100%", fontSize: 12, color: colors.textPri }}>
              <tbody>
                <Row k="Packets match the Table 1 row sum" v={budgets.packets_match ? "YES ✓" : "no"}
                     ok={budgets.packets_match} />
                <Row k="Bytes match the Table 1 row sum" v={budgets.bytes_match ? "YES ✓" : "no"}
                     ok={budgets.bytes_match} />
                <Row k="Reference" v={budgets.reference} />
              </tbody>
            </table>
            <p style={{ fontSize: 11, color: colors.textMute, marginTop: 8 }}>
              Table 1 prints three rows (WireGuard, Arnika, Rosenpass) and no
              total, so the "Table 1" figures are those rows added up, not a
              number the paper states. The check catches an edited per-phase
              budget; it is not a comparison with a printed total.
            </p>
          </>
        )}
      </Panel>
    </div>
  );
}

/** A panel whose request failed: say so, and say why, instead of spinning. */
function NotObserved({ why }: { why: string }) {
  return (
    <p role="status" style={{ color: colors.warn, fontSize: 12 }}>
      Not observed -- the request failed: {why}. Re-run to try again.
    </p>
  );
}

function Loading() {
  return <p style={{ color: colors.textMute, fontSize: 12 }}>Loading…</p>;
}

function Row({ k, v, ok }: { k: string; v: any; ok?: boolean }) {
  return (
    <tr>
      <td style={{ ...td, color: colors.textSec, width: 220 }}>{k}</td>
      <td style={{ ...td, color: ok === undefined ? colors.textPri
                    : ok ? colors.success : colors.warn,
                    fontWeight: ok ? 700 : 400 }}>{String(v ?? "—")}</td>
    </tr>
  );
}

const th: React.CSSProperties = { padding: "4px 8px", fontWeight: 600 };
const td: React.CSSProperties = { padding: "4px 8px" };
