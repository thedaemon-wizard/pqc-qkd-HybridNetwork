import { useEffect, useState } from "react";
import PageHeader from "../components/PageHeader";
import Panel from "../components/Panel";
import KPI from "../components/KPI";
import Button from "../components/Button";
import { colors } from "../lib/commonStyles";

/**
 * Implementation Verification page.
 *
 * Aggregates three independent "research-implementation verification" checks:
 *  1. Crypto-agility matrix — ML-KEM (encap/decap) + ML-DSA (sign/verify) across
 *     all NIST security levels via liboqs (+ PQClean test-binary presence).
 *  2. Key-rate cross-check — our closed-form Lo-Ma rate vs the independent
 *     TNO-Quantum qkd_key_rate engine (Apache-2.0) at the current config.
 *  3. Paper packet-budget match — arXiv:2604.05599 Table III handshake budgets.
 */

interface AgilityRow {
  algo: string; family: string; enabled: boolean; ok: boolean;
  pk_len?: number; ct_len?: number; ss_len?: number; sig_len?: number;
  pqclean_test_present?: boolean; error?: string;
}

export default function Verification() {
  const [agility, setAgility] = useState<any>(null);
  const [keyrate, setKeyrate] = useState<any>(null);
  const [budgets, setBudgets] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string>("");

  async function runAll() {
    setBusy(true); setErr("");
    try {
      const [a, k, b] = await Promise.allSettled([
        fetch("/api/pqc/agility", { method: "POST" }).then((r) => r.json()),
        fetch("/api/verify/keyrate").then((r) => r.json()),
        fetch("/api/verify/paper-budgets").then((r) => r.json()),
      ]);
      if (a.status === "fulfilled") setAgility(a.value);
      if (k.status === "fulfilled") setKeyrate(k.value);
      if (b.status === "fulfilled") setBudgets(b.value);
      if (a.status === "rejected" && k.status === "rejected") {
        setErr("Backend services unavailable.");
      }
    } finally { setBusy(false); }
  }

  useEffect(() => { runAll(); }, []);

  const fmt = (x: number | null | undefined, d = 3) =>
    typeof x === "number" ? x.toExponential(d) : "—";

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

      <div style={{ margin: "12px 0" }}>
        <Button variant="primary" onClick={runAll} disabled={busy}>
          {busy ? "Running…" : "Re-run all checks"}
        </Button>
        {err && <span style={{ marginLeft: 12, color: colors.danger, fontSize: 12 }}>{err}</span>}
      </div>

      {/* 1. Crypto-agility matrix */}
      <Panel title="1 · Crypto-Agility Matrix (liboqs — ML-KEM + ML-DSA)">
        {!agility ? <Loading /> : (
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
                  <th style={th}>liboqs</th><th style={th}>sizes (B)</th>
                  <th style={th}>PQClean ref</th>
                </tr>
              </thead>
              <tbody>
                {(agility.matrix as AgilityRow[]).map((r) => (
                  <tr key={r.algo} style={{ borderTop: `1px solid ${colors.border}` }}>
                    <td style={td}>{r.algo}</td>
                    <td style={td}>{r.family}</td>
                    <td style={{ ...td, color: r.ok ? colors.success : colors.danger,
                                  fontWeight: 700 }}>
                      {r.ok ? "PASS ✓" : (r.enabled ? "FAIL ✗" : "n/a")}
                    </td>
                    <td style={{ ...td, fontFamily: "monospace" }}>
                      {r.family === "KEM"
                        ? `pk ${r.pk_len ?? "–"} · ct ${r.ct_len ?? "–"} · ss ${r.ss_len ?? "–"}`
                        : `pk ${r.pk_len ?? "–"} · sig ${r.sig_len ?? "–"}`}
                    </td>
                    <td style={td}>{r.pqclean_test_present ? "present" : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p style={{ fontSize: 11, color: colors.textMute, marginTop: 8 }}>
              Crypto-agility = swapping the algorithm is one list edit; all NIST
              levels (512/768/1024 · 44/65/87) run through the same interface.
            </p>
          </>
        )}
      </Panel>

      {/* 2. Key-rate cross-check */}
      <Panel title="2 · Key-Rate Cross-Check (our closed form vs TNO-Quantum)">
        {!keyrate ? <Loading /> : keyrate.error && !keyrate.tno ? (
          <p style={{ color: colors.warn, fontSize: 12 }}>
            TNO engine unavailable: {keyrate.error}
          </p>
        ) : (
          <>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)",
                           gap: 12, marginBottom: 12 }}>
              <KPI label="Distance (km)" value={keyrate.distance_km ?? "—"} />
              <KPI label="Attenuation (dB)"
                   value={(keyrate.attenuation_db ?? 0).toFixed?.(1) ?? "—"} />
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
                <Row k="Same order of magnitude"
                     v={keyrate.same_order_of_magnitude ? "YES ✓ (independent agreement)" : "review"}
                     ok={keyrate.same_order_of_magnitude} />
              </tbody>
            </table>
            <p style={{ fontSize: 11, color: colors.textMute, marginTop: 8 }}>
              Two independent implementations (our closed-form Lo-Ma bound vs
              TNO-Quantum's optimiser) agree to order of magnitude — the rates
              differ because TNO optimises the intensity μ while ours uses the
              configured μ. Source: {keyrate.tno?.source ?? "—"}.
            </p>
          </>
        )}
      </Panel>

      {/* 3. Paper packet-budget match */}
      <Panel title="3 · Paper Packet-Budget Match (arXiv:2604.05599 Table III)">
        {!budgets ? <Loading /> : (
          <>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)",
                           gap: 12, marginBottom: 12 }}>
              <KPI label="Computed packets" value={budgets.computed_total_packets ?? "—"} />
              <KPI label="Paper packets" value={budgets.paper_total_packets ?? "—"} />
              <KPI label="Computed bytes" value={budgets.computed_total_bytes ?? "—"} />
              <KPI label="Paper bytes" value={budgets.paper_total_bytes ?? "—"} />
            </div>
            <table style={{ width: "100%", fontSize: 12, color: colors.textPri }}>
              <tbody>
                <Row k="Packets match paper" v={budgets.packets_match ? "YES ✓" : "no"}
                     ok={budgets.packets_match} />
                <Row k="Bytes match paper" v={budgets.bytes_match ? "YES ✓" : "no"}
                     ok={budgets.bytes_match} />
                <Row k="Reference" v={budgets.reference} />
              </tbody>
            </table>
          </>
        )}
      </Panel>
    </div>
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
