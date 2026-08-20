import { useEffect, useState } from "react";

/**
 * VPN Protocols page.
 *
 * Displays the two parallel quantum-secure VPN lanes:
 *   - WireGuard tunnel (kernel/boringtun)
 *   - strongSwan IPsec/IKEv2, RFC 9370 hybrid KE + RFC 8784 PPK
 *
 * The arnika HKDF(QKD ‖ PQC) output is consumed by BOTH lanes, through
 * different key-writer adapters: WireGuard via wgctrl netlink, strongSwan via
 * a native VICI client that installs the key as an RFC 8784 PPK.
 *
 * Everything shown here is parsed from the running daemon
 * (`swanctl --list-sas` / `--list-conns`); nothing on this page is a constant.
 */

interface VpnStatus {
  name: string;
  status: string;
  uptime?: string;
  active_sa?: number;
  /** Negotiated IKE_SA proposal, or null before the SA is up. */
  proposal?: string | null;
  last_handshake?: string | null;
  /** RFC 9370: an additional ML-KEM key exchange was negotiated. */
  pq_key_exchange?: boolean | null;
  /** RFC 8784: PPK identity configured on the connection. */
  ppk_id?: string | null;
  ppk_required?: boolean | null;
}

export default function VpnProtocols() {
  const [wg, setWg] = useState<VpnStatus | null>(null);
  const [ipsec, setIpsec] = useState<VpnStatus | null>(null);
  const [busy, setBusy] = useState(false);

  async function load() {
    try {
      const r = await fetch("/api/vpn/protocols");
      const j = await r.json();
      setWg(j.wireguard ?? null);
      setIpsec(j.ipsec ?? null);
    } catch { /* backend may be down */ }
  }
  useEffect(() => { load(); const t = setInterval(load, 3000); return () => clearInterval(t); }, []);

  return (
    <div>
      <h2 style={{ marginTop: 0 }}>VPN Protocols</h2>
      <p style={{ color: "#9aa9d8", maxWidth: 760 }}>
        The PoC ships <b>two Quantum-Secure VPN lanes</b>, both fed by the same
        arnika <code>HKDF-SHA3-256(QKD ‖ PQC)</code> output through different
        key-writer adapters:
      </p>
      <ul style={{ color: "#cbd6f5", lineHeight: 1.7, maxWidth: 760 }}>
        <li><b>WireGuard</b> — arnika derives a 32 B PSK and writes it into
            <code> wg0</code> through <code>wgctrl</code> netlink.</li>
        <li><b>strongSwan IPsec/IKEv2</b> — a native VICI client installs the
            same derived key as an <b>RFC 8784 Post-quantum Preshared Key</b>,
            on an IKE_SA negotiated with the <b>RFC 9370</b> hybrid
            <code> ecp256 + ke1_mlkem768</code>.</li>
      </ul>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16, marginTop: 16 }}>
        <Panel title="WireGuard (kernel / boringtun)" color="#3ddc84">
          {wg ? (
            <>
              <Row k="Status" v={<Badge text={wg.status} color={statusColor(wg.status)} />} />
              <Row k="Active SA" v={String(wg.active_sa ?? "-")} />
              <Row k="Proposal" v={wg.proposal ?? "ChaCha20-Poly1305 + Noise + PSK"} />
              <Row k="Last handshake" v={wg.last_handshake ?? "-"} />
            </>
          ) : <Loading />}
          <p style={{ marginTop: 10, fontSize: 12, color: "#9aa9d8" }}>
            PSK path: arnika (Go) → wgctrl netlink → wg0
          </p>
        </Panel>
        <Panel title="strongSwan IPsec/IKEv2 (RFC 9370 + RFC 8784)" color="#7c5cff">
          {ipsec ? (
            <>
              <Row k="Status" v={<Badge text={ipsec.status} color={statusColor(ipsec.status)} />} />
              <Row k="Active SA" v={String(ipsec.active_sa ?? "-")} />
              {/* No fallback constant: an unnegotiated SA must read as such. */}
              <Row k="Proposal" v={ipsec.proposal ?? "— not negotiated —"} />
              <Row k="PQ key exchange" v={ipsec.pq_key_exchange ? "RFC 9370 ML-KEM" : "—"} />
              <Row k="PPK (RFC 8784)" v={
                ipsec.ppk_id
                  ? `${ipsec.ppk_id}${ipsec.ppk_required ? " (required)" : " (optional)"}`
                  : "— not configured —"
              } />
              <Row k="Last handshake" v={ipsec.last_handshake ?? "-"} />
            </>
          ) : <Loading />}
          <p style={{ marginTop: 10, fontSize: 12, color: "#9aa9d8" }}>
            Key path: arnika → VICI <code>load-shared type=ppk</code> → charon reauth
          </p>
        </Panel>
      </div>

      <div style={{ marginTop: 24, background: "#0d1320", border: "1px solid #1d2741",
                     borderRadius: 8, padding: 14 }}>
        <h3 style={{ marginTop: 0, fontSize: 14, color: "#9aa9d8" }}>
          Two independent mechanisms — why both are needed
        </h3>
        <pre style={{ margin: 0, fontSize: 12, lineHeight: 1.5, color: "#cbd6f5", overflowX: "auto" }}>
{`RFC 9370 — strengthens the KEY EXCHANGE
   IKE_SA_INIT        KE payload   ECP-256
   IKE_INTERMEDIATE   KE payload   ML-KEM-768 (1184 B; encrypted, so fragmentable per RFC 9242)
   SKEYSEED(n) = prf(SK_d(n-1), SK(n) | Ni | Nr)      <- chained: secure if ANY round is

RFC 8784 — mixes the QKD key into the KEY SCHEDULE
   SK_d  = prf+(PPK, SK_d')
   SK_pi = prf+(PPK, SK_pi')
   SK_pr = prf+(PPK, SK_pr')

Why not a plain IKEv2 PSK: a PSK is consumed only in the IKE_AUTH AUTH payload
(RFC 7296 s2.15). It never enters SKEYSEED, so a QKD key delivered as a PSK adds
nothing against a harvest-now-decrypt-later adversary. The PPK does.

Known limits, stated plainly:
  - The PPK is NOT mixed into SKEYSEED, so SK_ei/SK_er of the initial IKE SA are
    not PPK-protected -- only SK_d (hence all Child SA KEYMAT) and the auth keys.
  - RFC 8784 covers the initial IKE SA only, so consuming fresh QKD material
    requires a reauthentication, not a rekey. RFC 9867 (Nov 2025) lifts this,
    but strongSwan 6.0.7 does not implement it yet.`}
        </pre>
      </div>
    </div>
  );
}

function Panel({ title, color, children }: { title: string; color: string; children: React.ReactNode }) {
  return (
    <div style={{ background: "#0d1320", border: `1px solid ${color}40`,
                   borderLeft: `4px solid ${color}`, borderRadius: 8, padding: 14 }}>
      <h3 style={{ margin: "0 0 10px 0", fontSize: 14, color }}>{title}</h3>
      {children}
    </div>
  );
}

function Row({ k, v }: { k: string; v: React.ReactNode }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between",
                   padding: "3px 0", fontSize: 13 }}>
      <span style={{ color: "#9aa9d8" }}>{k}</span>
      <span style={{ fontFamily: "monospace" }}>{v}</span>
    </div>
  );
}

function Badge({ text, color }: { text: string; color: string }) {
  return (
    <span style={{ display: "inline-block", padding: "2px 8px", borderRadius: 12,
                    background: color, color: "#fff", fontSize: 11 }}>{text}</span>
  );
}

function statusColor(s: string): string {
  if (s === "running" || s === "established") return "#3ddc84";
  if (s === "restarting" || s === "rekeying") return "#f5a623";
  // "error" means swanctl itself failed -- charon is not answering. That must
  // read as a fault, not fall through to the neutral colour that also means
  // "absent", or a dead daemon looks unremarkable.
  if (s === "stopped" || s === "down" || s === "error") return "#e25555";
  return "#445";
}

function Loading() {
  return <div style={{ color: "#6b7796", fontSize: 12 }}>Loading…</div>;
}
