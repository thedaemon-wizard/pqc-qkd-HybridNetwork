import { useEffect, useState } from "react";
import { getStack, postStack, type StackItem } from "../api";

const STATUS_COLOR: Record<string, string> = {
  running: "#3ddc84", restarting: "#f5a623", created: "#5b8def",
  exited: "#e25555", paused: "#a06bff", dead: "#e25555",
  absent: "#445", unknown: "#445",
};

export default function Overview() {
  const [stack, setStack] = useState<StackItem[]>([]);

  async function refresh() { setStack(await getStack()); }
  useEffect(() => {
    refresh();
    const t = setInterval(refresh, 3000);
    return () => clearInterval(t);
  }, []);

  return (
    <div>
      <h2 style={{ marginTop: 0 }}>Architecture &amp; Live Status</h2>
      <p style={{ color: "#9aa9d8", maxWidth: 720 }}>
        3層モデル: (1) BB84-KME → ETSI 014 で QKD 鍵を供給。
        (2) 各ノードで Rosenpass が PQC 鍵を生成。
        (3) arnika が HKDF-SHA3-256 で両者を融合し、WireGuard PSK を 30秒毎に更新。
      </p>

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
                    <span style={{
                      display: "inline-block", padding: "2px 8px", borderRadius: 12,
                      background: STATUS_COLOR[s.status] || "#445",
                      color: "#fff", fontSize: 11,
                    }}>{s.status}</span>
                  </td>
                  <td>
                    <button onClick={() => postStack("restart", s.name)}
                            style={btnStyle}>restart</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

function ArchPanel() {
  return (
    <div style={{ background: "#0d1320", padding: 16, borderRadius: 8, border: "1px solid #1d2741" }}>
      <h3 style={{ marginTop: 0 }}>Layered Architecture (from PDF)</h3>
      <svg viewBox="0 0 420 280" style={{ width: "100%" }}>
        {/* E2E Layer */}
        <rect x="20" y="20" width="380" height="60" rx="6" fill="#332247" stroke="#7c5cff" />
        <text x="210" y="48" fill="#d8c8ff" textAnchor="middle" fontSize="14">End-to-End: Rosenpass PQC handshake (ML-KEM-768)</text>
        <text x="210" y="66" fill="#9d8fc8" textAnchor="middle" fontSize="11">writes pqc.psk file</text>
        {/* Transport Layer */}
        <rect x="20" y="100" width="380" height="60" rx="6" fill="#3a2a18" stroke="#ff9442" />
        <text x="210" y="128" fill="#ffd9b8" textAnchor="middle" fontSize="14">Transport: Arnika (HKDF-SHA3-256 fuses QKD‖PQC)</text>
        <text x="210" y="146" fill="#c8a47e" textAnchor="middle" fontSize="11">ETSI GS QKD 014 client + WireGuard netlink</text>
        {/* Hop Layer */}
        <rect x="20" y="180" width="380" height="60" rx="6" fill="#1f3322" stroke="#3ddc84" />
        <text x="210" y="208" fill="#c4f5d8" textAnchor="middle" fontSize="14">Hop: WireGuard tunnel (PSK rotation every 30s)</text>
        <text x="210" y="226" fill="#84c89c" textAnchor="middle" fontSize="11">ChaCha20-Poly1305 + Noise + PSK</text>
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
