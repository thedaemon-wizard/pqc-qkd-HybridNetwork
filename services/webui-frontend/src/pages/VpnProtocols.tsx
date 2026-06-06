import { useEffect, useState } from "react";

/**
 * VPN Protocols page (Phase 9-A).
 *
 * Displays the two parallel quantum-secure VPN lanes:
 *   - WireGuard tunnel (Phase 0-7, kernel/boringtun)
 *   - strongSwan IPsec/IKEv2 with RFC 9370 ML-KEM-768 hybrid (Phase 9-A)
 *
 * The arnika HKDF(QKD ‖ PQC) output is consumed by BOTH lanes via different
 * mechanisms: WireGuard receives the PSK via netlink; strongSwan receives
 * it through the vici socket bridge.
 */

interface VpnStatus {
  name: string;
  status: string;
  uptime?: string;
  active_sa?: number;
  proposal?: string;
  last_handshake?: string;
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
      <h2 style={{ marginTop: 0 }}>VPN Protocols (Phase 9-A)</h2>
      <p style={{ color: "#9aa9d8", maxWidth: 760 }}>
        The PoC ships <b>two equally-supported Quantum-Secure VPN lanes</b>:
      </p>
      <ul style={{ color: "#cbd6f5", lineHeight: 1.7, maxWidth: 760 }}>
        <li><b>WireGuard</b> — arnika derives a 32 B PSK via HKDF(QKD ‖ PQC) and
            writes it into <code>wg0</code> through netlink, rotating every 30 s.</li>
        <li><b>strongSwan IPsec/IKEv2</b> — establishes IKE_SA with the
            <b> RFC 9370</b> ML-KEM-768 hybrid (ECP-256 + KE1=ml_kem_768);
            arnika re-injects the PSK over the vici socket.</li>
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
        <Panel title="strongSwan IPsec/IKEv2 (RFC 9370 hybrid)" color="#7c5cff">
          {ipsec ? (
            <>
              <Row k="Status" v={<Badge text={ipsec.status} color={statusColor(ipsec.status)} />} />
              <Row k="Active SA" v={String(ipsec.active_sa ?? "-")} />
              <Row k="Proposal" v={ipsec.proposal ?? "aes256gcm16-sha256-ecp256-ke1_ml_kem_768"} />
              <Row k="Last handshake" v={ipsec.last_handshake ?? "-"} />
            </>
          ) : <Loading />}
          <p style={{ marginTop: 10, fontSize: 12, color: "#9aa9d8" }}>
            PSK path: arnika → arnika-vici-bridge.sh → swanctl --load-creds → charon
          </p>
        </Panel>
      </div>

      <div style={{ marginTop: 24, background: "#0d1320", border: "1px solid #1d2741",
                     borderRadius: 8, padding: 14 }}>
        <h3 style={{ marginTop: 0, fontSize: 14, color: "#9aa9d8" }}>RFC 9370 hybrid key exchange</h3>
        <pre style={{ margin: 0, fontSize: 12, lineHeight: 1.5, color: "#cbd6f5" }}>
{`IKE_SA_INIT  (RFC 9370 §2)
   ├─ KE  payload  (classical)   ECP-256 public key (64 B)
   └─ KEi payload  (post-quantum) ML-KEM-768 public key (1184 B; IKEv2 fragmentation required)

Derived PSK = HKDF-Extract(salt, classical_secret ‖ pq_secret) ‖ HKDF-Expand(...)

Forward secrecy is preserved as long as at least one of the classical and PQ secrets remains unbroken.`}
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
  if (s === "stopped" || s === "down") return "#e25555";
  return "#445";
}

function Loading() {
  return <div style={{ color: "#6b7796", fontSize: 12 }}>Loading…</div>;
}
