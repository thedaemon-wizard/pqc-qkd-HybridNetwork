import { NavLink, Route, Routes } from "react-router-dom";
import Overview from "./pages/Overview";
import BB84 from "./pages/BB84";
import KeyFlow from "./pages/KeyFlow";
import Topology from "./pages/Topology";
import Benchmarks from "./pages/Benchmarks";
import Console from "./pages/Console";
import PhysicsParams from "./pages/PhysicsParams";
import PQCValidator from "./pages/PQCValidator";
import HIL from "./pages/HIL";
import VpnProtocols from "./pages/VpnProtocols";
import QuantumSecureE2E from "./pages/QuantumSecureE2E";

const nav = [
  { to: "/",            label: "Overview" },
  { to: "/e2e",         label: "Quantum-Secure E2E ★" },
  { to: "/bb84",        label: "BB84 Live" },
  { to: "/keyflow",     label: "Key Flow" },
  { to: "/topology",    label: "Topology" },
  { to: "/benchmarks",  label: "Benchmarks" },
  { to: "/console",     label: "Console" },
  { to: "/physics",     label: "Physics Params" },
  { to: "/pqc",         label: "PQC Validator" },
  { to: "/hil",         label: "Hardware-In-Loop" },
  { to: "/vpn",         label: "VPN Protocols" },
];

export default function App() {
  return (
    <div style={{ display: "grid", gridTemplateColumns: "220px 1fr", minHeight: "100vh" }}>
      <aside style={{ background: "#0d1320", padding: "1.5rem 1rem", borderRight: "1px solid #1d2741" }}>
        <h1 style={{ fontSize: 18, marginTop: 0, marginBottom: 24, lineHeight: 1.3 }}>
          PQC-QKD<br />Hybrid PoC
        </h1>
        <nav style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          {nav.map(n => (
            <NavLink
              key={n.to}
              to={n.to}
              end={n.to === "/"}
              style={({ isActive }) => ({
                padding: "8px 12px",
                borderRadius: 6,
                textDecoration: "none",
                color: isActive ? "#fff" : "#9aa9d8",
                background: isActive ? "#1a2440" : "transparent",
              })}
            >
              {n.label}
            </NavLink>
          ))}
        </nav>
        <div style={{ marginTop: 36, fontSize: 11, color: "#6b7796", lineHeight: 1.5 }}>
          ETSI GS QKD 014<br />
          ML-KEM-768 + HKDF-SHA3-256<br />
          arnika-vq · liboqs · rosenpass
        </div>
      </aside>
      <main style={{ padding: "1.5rem 2rem" }}>
        <Routes>
          <Route path="/" element={<Overview />} />
          <Route path="/bb84" element={<BB84 />} />
          <Route path="/keyflow" element={<KeyFlow />} />
          <Route path="/topology" element={<Topology />} />
          <Route path="/benchmarks" element={<Benchmarks />} />
          <Route path="/console" element={<Console />} />
          <Route path="/physics" element={<PhysicsParams />} />
          <Route path="/pqc" element={<PQCValidator />} />
          <Route path="/hil" element={<HIL />} />
          <Route path="/vpn" element={<VpnProtocols />} />
          <Route path="/e2e" element={<QuantumSecureE2E />} />
        </Routes>
      </main>
    </div>
  );
}
