import { useEffect, useState } from "react";
import { getStack, postStack, type StackItem } from "../api";
import PageHeader from "../components/PageHeader";
import ExportToolbar from "../components/ExportToolbar";
import { useContainerControl } from "../lib/useConfig";

const STATUS_COLOR: Record<string, string> = {
  running: "#3ddc84", restarting: "#f5a623", created: "#5b8def",
  exited: "#e25555", paused: "#a06bff", dead: "#e25555",
  absent: "#445", unknown: "#445",
};

/** What the row should SAY, which is not always the raw docker status.
 *
 * `absent` means "no such container". For the three profile-gated services --
 * qkdnetsim-kme (crossvalidate), alice-ipsec and bob-ipsec (ipsec) -- that is
 * the expected state on the default stack, because the base compose file does
 * not define them at all. Rendering it with the same grey chip as a container
 * that died made three of ten rows read as failures on a healthy stack, and
 * the page offered no way to tell which reading was correct.
 *
 * The backend now sends `optional`, `profile` and `compose_file`; this only
 * decides how to show them. A row without those fields is unchanged. */
function chip(s: StackItem): { label: string; color: string; title?: string } {
  if (s.optional && s.status === "absent") {
    return {
      label: `not started (${s.profile})`,
      color: "#3a4a6b",
      title: s.note,
    };
  }
  return { label: s.status, color: STATUS_COLOR[s.status] || "#445", title: s.note };
}

export default function Overview() {
  const [stack, setStack] = useState<StackItem[]>([]);
  // `useContainerControl`, not `useDemoMode`. Its own doc comment prescribes
  // exactly this -- "Gate the UI on this rather than on !demo_mode: container
  // control is opt-in server-side, so 'not a demo' no longer implies 'control
  // is available'" -- and this page never adopted it.
  //
  // The two predicates disagree in one configuration, and it is the one the
  // public demo runs: /api/config reports demo_mode false AND
  // container_control false, so `!demo` rendered a restart button for all ten
  // containers while the endpoint refused every click with 403.
  const canControl = useContainerControl();
  const [actionError, setActionError] = useState<string>("");

  async function refresh() { setStack(await getStack()); }
  useEffect(() => {
    refresh();
    const t = setInterval(refresh, 3000);
    return () => clearInterval(t);
  }, []);

  return (
    <div>
      <PageHeader
        title="Architecture & Live Status"
        subtitle={<>Three-layer model: (1) <code>bb84-kme</code> delivers QKD keys over ETSI 014.
          (2) A Rosenpass sidecar at each node produces PQC keys.
          (3) <code>arnika</code> fuses both via HKDF-SHA3-256 and installs the result.
          {" "}<b>Two VPN lanes consume that key.</b> The <b>WireGuard</b> lane takes it as a
          preshared key, which enters the Noise_IKpsk2 chaining key. The <b>IPsec/IKEv2</b> lane
          (<code>alice-ipsec</code>/<code>bob-ipsec</code>) takes it as an
          {" "}<b>RFC 8784 PPK</b> over strongSwan&rsquo;s VICI socket, alongside RFC 9370 ML-KEM-768;
          see <a href="/vpn">VPN Protocols</a>. Rotation is configured at 30 s, but the interval
          is when arnika <i>attempts</i> a rotation, not a guarantee: measured gaps on the public
          host ran 30&ndash;241 s, so count rotations over a window rather than dividing by 30.</>}
      />
      <div style={{ marginBottom: 12 }}>
        <ExportToolbar
          name="overview"
          logService="webui-backend"
          pngTargetSelector="#overview-arch-svg"
          jsonProvider={() => ({ stack })}
        />
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16, marginTop: 20 }}>
        <ArchPanel />
        <div>
          <h3>Container Status</h3>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
            <thead>
              <tr style={{ textAlign: "left", color: "#6b7796" }}>
                <th>Name</th><th>Status</th><th></th>
              </tr>
            </thead>
            <tbody>
              {stack.map(s => (
                <tr key={s.name} style={{ borderTop: "1px solid #1d2741" }}>
                  <td style={{ padding: "8px 4px" }}>{s.name}</td>
                  <td>
                    {(() => { const c = chip(s); return (
                      <span title={c.title} style={{
                        display: "inline-block", padding: "2px 8px", borderRadius: 12,
                        background: c.color, color: "#fff", fontSize: 11,
                      }}>{c.label}</span>
                    ); })()}
                  </td>
                  <td>
                    {canControl ? (
                      // The promise is consumed. `onClick={() => postStack(...)}`
                      // discarded it, so even a genuine 500 from the handler was
                      // invisible -- no state change, no console entry, not even
                      // an unhandled rejection, because the refusal RESOLVED.
                      <button
                        onClick={async () => {
                          setActionError("");
                          try {
                            await postStack("restart", s.name);
                            await refresh();
                          } catch (e) {
                            setActionError(`${s.name}: ${e instanceof Error ? e.message : String(e)}`);
                          }
                        }}
                        style={btnStyle}
                      >restart</button>
                    ) : (
                      <span style={{ fontSize: 11, color: "#6b7796" }}
                            title="container control is disabled on this deployment (/api/config)">—</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {actionError && (
            <p role="alert" style={{ color: "#e25555", fontSize: 12, marginTop: 8 }}>
              {actionError}
            </p>
          )}
        </div>
      </div>
    </div>
  );
}

function ArchPanel() {
  return (
    <div style={{ background: "#0d1320", padding: 16, borderRadius: 8, border: "1px solid #1d2741" }}>
      <h3 style={{ marginTop: 0 }}>Layered Architecture (from arXiv:2604.05599)</h3>
      <svg id="overview-arch-svg" viewBox="0 0 420 280" style={{ width: "100%" }}>
        {/* E2E Layer */}
        <rect x="20" y="20" width="380" height="60" rx="6" fill="#332247" stroke="#7c5cff" />
        {/* Two lines because SVG text does not wrap. Correcting the KEM name
            lengthened this label to 420px inside a 380px box, so it spilled
            20px past both borders. Measured with getComputedTextLength, not
            eyeballed -- see checklist 4.2.5. */}
        <text x="210" y="44" fill="#d8c8ff" textAnchor="middle" fontSize="14">End-to-End: Rosenpass handshake</text>
        <text x="210" y="62" fill="#9d8fc8" textAnchor="middle" fontSize="11">McEliece 460896 + Kyber512 — writes pqc.psk file</text>
        {/* Transport Layer */}
        <rect x="20" y="100" width="380" height="60" rx="6" fill="#3a2a18" stroke="#ff9442" />
        <text x="210" y="128" fill="#ffd9b8" textAnchor="middle" fontSize="14">Transport: Arnika (HKDF-SHA3-256 fuses QKD‖PQC)</text>
        <text x="210" y="146" fill="#c8a47e" textAnchor="middle" fontSize="11">ETSI 014 client + key writers: WireGuard netlink / strongSwan VICI</text>
        {/* Hop Layer */}
        <rect x="20" y="180" width="380" height="60" rx="6" fill="#1f3322" stroke="#3ddc84" />
        <text x="210" y="204" fill="#c4f5d8" textAnchor="middle" fontSize="14">Hop: WireGuard tunnel, or IPsec/IKEv2 (RFC 8784 PPK)</text>
        <text x="210" y="220" fill="#84c89c" textAnchor="middle" fontSize="11">ChaCha20-Poly1305 + Noise_IKpsk2 + PSK</text>
        <text x="210" y="234" fill="#84c89c" textAnchor="middle" fontSize="11">AES-GCM-256 + ML-KEM-768 (RFC 9370) + PPK</text>
        {/* arrows */}
        <line x1="210" y1="80" x2="210" y2="100" stroke="#5b8def" strokeWidth="1.5" markerEnd="url(#arr)" />
        <line x1="210" y1="160" x2="210" y2="180" stroke="#5b8def" strokeWidth="1.5" markerEnd="url(#arr)" />
        <defs>
          <marker id="arr" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto">
            <path d="M 0 0 L 10 5 L 0 10 z" fill="#5b8def" />
          </marker>
        </defs>
      </svg>
    </div>
  );
}

const btnStyle: React.CSSProperties = {
  background: "#1a2440", color: "#d8e1ff", border: "1px solid #2a3760",
  borderRadius: 4, padding: "2px 10px", fontSize: 11, cursor: "pointer",
};
