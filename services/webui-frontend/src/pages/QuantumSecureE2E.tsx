import { useEffect, useRef, useState } from "react";
import PageHeader from "../components/PageHeader";
import ExportToolbar from "../components/ExportToolbar";

/**
 * Quantum-Secure E2E Simulation (Phase 10).
 *
 * Visualises the 4-phase data exchange from the reference architecture image:
 *   Phase 1  Quantum Plane           — bb84-kme keys appear
 *   Phase 2  QKD Key IDs (ETSI 014)  — arnika fetches via enc_keys / dec_keys
 *   Phase 3  PQC Handshake           — HKDF-SHA3-256 combines QKD ‖ PQC
 *   Phase 4  Data Exchange           — ChaCha20-Poly1305 encrypted ping payloads
 *
 * Drives the FastAPI orchestrator via REST and subscribes to /ws/e2e for live
 * phase transitions, byte counters, derived-PSK prefix and QKD key IDs.
 */

type E2EState = {
  status: "idle" | "running" | "paused";
  current_phase: number;
  phase_name: string;
  mode: "A" | "B" | "C";
  mode_label: string;
  completed_cycles: number;
  total_bytes_encrypted: number;
  total_packets: number;
  last_qkd_key_id: string;
  last_psk_prefix_hex: string;
  last_error: string;
  rate_bps: number;
  history: {
    phase: number; name: string;
    started_at: number; completed_at: number | null;
    detail: Record<string, unknown>;
  }[];
};

const MODE_COLOR: Record<string, string> = {
  A: "#f0a020",  // QKD-only — orange
  B: "#e91e63",  // PQC-only — pink
  C: "#e25555",  // Hybrid   — red
};

const PHASE_LABELS = [
  "1. Quantum Plane",
  "2. QKD Key IDs (ETSI 014)",
  "3. PQC Handshake (HKDF-SHA3)",
  "4. Data Exchange (ChaCha20-Poly1305)",
];

export default function QuantumSecureE2E() {
  const [state, setState] = useState<E2EState | null>(null);
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    const proto = location.protocol === "https:" ? "wss:" : "ws:";
    const ws = new WebSocket(`${proto}//${location.host}/ws/e2e`);
    ws.onmessage = (ev) => {
      try { setState(JSON.parse(ev.data)); } catch { /* ignore */ }
    };
    wsRef.current = ws;
    return () => ws.close();
  }, []);

  async function ctl(action: "start" | "pause" | "resume" | "reset" | "step") {
    await fetch(`/api/e2e/${action}`, { method: "POST" });
  }
  async function setMode(mode: "A" | "B" | "C") {
    await fetch("/api/e2e/mode", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mode }),
    });
  }

  const status = state?.status ?? "idle";
  const phase = state?.current_phase ?? 0;
  const mode = state?.mode ?? "C";

  return (
    <div>
      <PageHeader
        title="Quantum-Secure E2E Simulation (Phase 10)"
        subtitle={<>Run and visualise the live <b>4-phase Data Exchange</b> between Alice
          and Bob. <code>bb84-kme</code> (SimQN backend) produces real ETSI 014 keys,
          the orchestrator fuses QKD ‖ PQC via HKDF-SHA3-256, and the final phase
          encrypts packets with ChaCha20-Poly1305 keyed by the derived PSK.
          Use the Run / Pause / Reset / Step buttons below to drive the state machine.</>}
      />

      {/* Export toolbar — between explanation text and simulation diagram.
          PNG / Animation capture target is restricted to the ArchSvg so the
          exported artefacts contain ONLY the architecture diagram. */}
      <div style={{ marginBottom: 12 }}>
        <ExportToolbar
          name="e2e-architecture"
          logService="webui-backend"
          pngTargetSelector="#e2e-arch-svg"
          jsonProvider={() => state ?? { status: "loading" }}
        />
      </div>

      {/* Architecture diagram — Image 1 layout (PNG/GIF capture target) */}
      <div id="e2e-arch-svg-wrap">
        <ArchSvg mode={mode} phase={phase} />
      </div>

      {/* Mode A/B/C buttons */}
      <div style={{ display: "flex", gap: 8, margin: "16px 0", flexWrap: "wrap",
                     alignItems: "center" }}>
        <span style={{ color: "#9aa9d8", fontSize: 13 }}>Mode:</span>
        {(["A", "B", "C"] as const).map((m) => (
          <button key={m} onClick={() => setMode(m)}
                  style={modeBtn(m === mode, MODE_COLOR[m])}>
            {m === "A" && "A · QKD-only"}
            {m === "B" && "B · PQC-only"}
            {m === "C" && "C · Hybrid (QKD ‖ PQC)"}
          </button>
        ))}
      </div>

      {/* Operation controls */}
      <div style={{ display: "flex", gap: 8, marginBottom: 16 }}>
        <button onClick={() => ctl("start")} disabled={status === "running"}
                style={primaryBtn("#3ddc84")}>▶ Run</button>
        <button onClick={() => ctl("pause")} disabled={status !== "running"}
                style={primaryBtn("#f5a623")}>⏸ Pause</button>
        <button onClick={() => ctl("resume")} disabled={status !== "paused"}
                style={primaryBtn("#7c5cff")}>▶ Resume</button>
        <button onClick={() => ctl("reset")} style={primaryBtn("#e25555")}>⏹ Reset</button>
        <button onClick={() => ctl("step")} style={primaryBtn("#5b8def")}>⏭ Step</button>
        <Badge text={`status: ${status}`}
               color={status === "running" ? "#3ddc84"
                      : status === "paused" ? "#f5a623" : "#445"} />
      </div>

      {/* Phase progress strip */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)",
                     gap: 8, marginBottom: 16 }}>
        {PHASE_LABELS.map((lbl, i) => {
          const idx = i + 1;
          const active = phase === idx;
          const done = state && state.history.some(
            (h) => h.phase === idx && h.completed_at);
          return (
            <div key={lbl} data-phase={idx}
                 style={{
                   padding: "10px 12px", borderRadius: 8,
                   background: active ? "#1a2440"
                              : done ? "#0d1f1a" : "#0d1320",
                   border: `1px solid ${active ? "#e25555"
                              : done ? "#3ddc84" : "#1d2741"}`,
                   color: active ? "#fff" : done ? "#3ddc84" : "#6b7796",
                   fontSize: 13, fontWeight: active ? 700 : 400,
                   transition: "all 0.2s",
                   boxShadow: active ? "0 0 12px #e2555560" : "none",
                 }}>
              {lbl}
              {active && <span style={{ marginLeft: 8 }}>●</span>}
              {done && !active && <span style={{ marginLeft: 8 }}>✓</span>}
            </div>
          );
        })}
      </div>

      {/* KPI cards */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)",
                     gap: 12, marginBottom: 16 }}>
        <KPI label="Completed cycles" value={state?.completed_cycles ?? 0} />
        <KPI label="Packets encrypted" value={state?.total_packets ?? 0} />
        <KPI label="Bytes encrypted (×10³)"
             value={Math.round((state?.total_bytes_encrypted ?? 0) / 1000)} />
        <KPI label="Throughput (Mbps)"
             value={((state?.rate_bps ?? 0) / 1e6).toFixed(2)} />
      </div>

      {/* Latest derived material */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
        <Panel title="Latest QKD key (ETSI 014)">
          <Row k="key_ID" v={state?.last_qkd_key_id || "—"} />
        </Panel>
        <Panel title="Latest derived PSK (HKDF-SHA3-256)">
          <Row k="hex prefix (16 of 64)" v={state?.last_psk_prefix_hex || "—"} />
        </Panel>
      </div>

      {state?.last_error && (
        <div style={{ marginTop: 14, padding: 10, background: "#3a1818",
                       border: "1px solid #e25555", borderRadius: 6,
                       color: "#ffd6d6", fontSize: 12 }}>
          last error: {state.last_error}
        </div>
      )}

      {/* Phase history (last 8) */}
      <Panel title="Phase history (last 8)">
        <table style={{ width: "100%", fontSize: 12, color: "#cbd6f5" }}>
          <thead>
            <tr style={{ color: "#6b7796" }}>
              <th align="left">phase</th><th align="left">name</th>
              <th align="left">duration (ms)</th><th align="left">detail</th>
            </tr>
          </thead>
          <tbody>
            {(state?.history ?? []).slice(-8).reverse().map((h, i) => {
              const dur = h.completed_at
                ? ((h.completed_at - h.started_at) * 1000).toFixed(0) : "…";
              return (
                <tr key={i} style={{ borderTop: "1px solid #1d2741" }}>
                  <td style={{ padding: "4px 0" }}>{h.phase}</td>
                  <td>{h.name}</td>
                  <td>{dur}</td>
                  <td style={{ fontFamily: "monospace", fontSize: 11 }}>
                    {JSON.stringify(h.detail).slice(0, 80)}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </Panel>
    </div>
  );
}

// ============== visual sub-components ==============

function ArchSvg({ mode, phase }: { mode: string; phase: number }) {
  // Highlight rules:
  //   mode "A" (QKD-only) -> orange path active in phase 1-2
  //   mode "B" (PQC-only) -> pink path active in phase 3
  //   mode "C" (Hybrid)   -> red HKDF box active in phase 3, tunnel in phase 4
  //
  // Layout v2 (Phase 11): image-faithful 1240×620 viewBox with three dashed
  // boundary boxes (VPN scope, Secure Application Entity, QKD Infrastructure),
  // top key-color legend (A/B/C with key icons mirrored on Site A and B),
  // center "VPN" lock icon, ETSI-Interface "E" markers, bottom-left 4-item
  // legend (A/B/C/E), and three separated bottom rows for the PQC KEY
  // exchange, QKD key_ID exchange, and Quantum Channel.
  const hot = (cond: boolean) =>
    cond ? "#e25555" : "#3a4a78";
  const dimUnless = (cond: boolean) => (cond ? 1 : 0.3);
  return (
    <div style={{ background: "#0d1320", border: "1px solid #1d2741",
                   borderRadius: 8, padding: 12, marginBottom: 10 }}>
      <svg id="e2e-arch-svg" viewBox="0 0 1240 620" style={{ width: "100%" }}
           role="img" aria-label="Quantum-secure VPN architecture (Image 1 faithful)">
        {/* ───── Dashed boundary boxes (z=0, back) ───── */}
        {/* Quantum Key Distribution Infrastructure (left + right, blue) */}
        <rect x="10" y="100" width="130" height="380" rx="6"
              fill="none" stroke="#5b8def" strokeWidth="1.5" strokeDasharray="5 4" />
        <text x="75" y="120" fill="#5b8def" fontSize="11" textAnchor="middle">Quantum Key</text>
        <text x="75" y="134" fill="#5b8def" fontSize="11" textAnchor="middle">Distribution</text>
        <text x="75" y="148" fill="#5b8def" fontSize="11" textAnchor="middle">Infrastructure</text>

        <rect x="1100" y="100" width="130" height="380" rx="6"
              fill="none" stroke="#5b8def" strokeWidth="1.5" strokeDasharray="5 4" />
        <text x="1165" y="120" fill="#5b8def" fontSize="11" textAnchor="middle">Quantum Key</text>
        <text x="1165" y="134" fill="#5b8def" fontSize="11" textAnchor="middle">Distribution</text>
        <text x="1165" y="148" fill="#5b8def" fontSize="11" textAnchor="middle">Infrastructure</text>

        {/* VPN scope (red dashed, mid-large) */}
        <rect x="150" y="60" width="940" height="440" rx="8"
              fill="none" stroke="#e25555" strokeWidth="1.5" strokeDasharray="6 4" />
        <text x="620" y="76" fill="#e25555" fontSize="13" textAnchor="middle"
              fontStyle="italic">VPN scope</text>

        {/* Secure Application Entity (purple dashed, inside VPN scope per-site) */}
        <rect x="180" y="160" width="420" height="220" rx="6"
              fill="none" stroke="#7c5cff" strokeWidth="1.4" strokeDasharray="5 3" />
        <text x="390" y="375" fill="#7c5cff" fontSize="11" textAnchor="middle">
          Secure Application Entity
        </text>
        <rect x="640" y="160" width="420" height="220" rx="6"
              fill="none" stroke="#7c5cff" strokeWidth="1.4" strokeDasharray="5 3" />
        <text x="850" y="375" fill="#7c5cff" fontSize="11" textAnchor="middle">
          Secure Application Entity
        </text>

        {/* ───── Center divider + VPN lock (z=1) ───── */}
        <line x1="620" y1="50" x2="620" y2="580" stroke="#3a4a78"
              strokeWidth="1.5" strokeDasharray="6 5" />
        <text x="260" y="48" fill="#cbd6f5" fontSize="14" textAnchor="middle"
              fontWeight={700}>Site A</text>
        <text x="980" y="48" fill="#cbd6f5" fontSize="14" textAnchor="middle"
              fontWeight={700}>Site B</text>
        {/* VPN lock icon at center divider */}
        <g transform="translate(620,270)">
          <circle r="14" fill="#e25555" opacity={dimUnless(phase === 4)} />
          <rect x="-7" y="-3" width="14" height="11" rx="1" fill="#fff"
                opacity={dimUnless(phase === 4)} />
          <path d="M -4,-3 L -4,-7 Q -4,-11 0,-11 Q 4,-11 4,-7 L 4,-3"
                stroke="#fff" strokeWidth="1.5" fill="none"
                opacity={dimUnless(phase === 4)} />
          <text y="26" fill="#e25555" fontSize="10" textAnchor="middle"
                fontWeight={700}>VPN</text>
        </g>

        {/* ───── Top key-color legend (A/B/C with key icons), mirrored ───── */}
        <KeyLegend x={280} flip={false} mode={mode} />
        <KeyLegend x={960} flip={true}  mode={mode} />

        {/* ───── KMS keystores (z=2) ───── */}
        <KmsKeystore x={40}  active={phase === 2} />
        <KmsKeystore x={1100} active={phase === 2} mirror />

        {/* ETSI Interface "E" markers (orange circles, on KMS->ARNIKA edge) */}
        <ETSIBadge x={172} y={290} active={phase === 2} />
        <ETSIBadge x={1068} y={290} active={phase === 2} />

        {/* ───── Site A inner boxes (z=3, top→bottom for vertical clarity) ───── */}
        <SiteBox x={196} y={188} label="ARNIKA" tag="KEY-CONTROL" color="#f0a020"
                 hot={phase === 2 || phase === 3} />
        <SiteBox x={326} y={188} label="ROSENPASS" tag="PQC function" color="#e91e63"
                 hot={(mode === "B" || mode === "C") && phase === 3} />
        <SiteBox x={456} y={188} label="WIREGUARD" tag="VPN function" color="#7c5cff"
                 hot={phase === 4} />

        {/* Site B (mirrored) */}
        <SiteBox x={636} y={188} label="WIREGUARD" tag="VPN function" color="#7c5cff"
                 hot={phase === 4} />
        <SiteBox x={766} y={188} label="ROSENPASS" tag="PQC function" color="#e91e63"
                 hot={(mode === "B" || mode === "C") && phase === 3} />
        <SiteBox x={896} y={188} label="ARNIKA" tag="KEY-CONTROL" color="#f0a020"
                 hot={phase === 2 || phase === 3} />

        {/* HKDF SHA3 indicator (z=4) — inside ARNIKA */}
        {/* Phase 14-C: was x=244 (ARNIKA mid-x=250 ± 38 = 212..304, badge r=14
            covers 230..258 → collided with title text @ x=250). Shifted to
            x=222 (top-left corner of box, clear of title and tag rows). */}
        <HkdfBadge x={222} y={188 + 70 - 8} active={mode === "C" && phase === 3} />
        <HkdfBadge x={922} y={188 + 70 - 8} active={mode === "C" && phase === 3} />

        {/* ───── KMS→ARNIKA QKD KEY arrows (orange dashed, z=5) ───── */}
        {/* Phase 14-C: labels moved out of ARNIKA box (was y=232 colliding with
            tag y=238) → up to y=208 (clear gap above box top y=188). */}
        <line x1="100" y1="240" x2="196" y2="240"
              stroke="#f0a020" strokeWidth="2"
              opacity={dimUnless(phase === 2)} />
        <text x="148" y="208" fill="#f0a020" fontSize="10" textAnchor="middle">QKD KEY</text>
        <line x1="1140" y1="240" x2="1044" y2="240"
              stroke="#f0a020" strokeWidth="2"
              opacity={dimUnless(phase === 2)} />
        <text x="1092" y="208" fill="#f0a020" fontSize="10" textAnchor="middle">QKD KEY</text>

        {/* ARNIKA→KMS key_ID arrows (green, z=5) — slightly below */}
        {/* Phase 14-C: key_ID label y=278 → y=288 (was 10 px from box border, now 20 px). */}
        <line x1="196" y1="265" x2="100" y2="265"
              stroke="#3ddc84" strokeWidth="1.5" strokeDasharray="4 3"
              opacity={dimUnless(phase === 2)} />
        <text x="148" y="288" fill="#3ddc84" fontSize="9" textAnchor="middle">key_ID</text>
        <line x1="1044" y1="265" x2="1140" y2="265"
              stroke="#3ddc84" strokeWidth="1.5" strokeDasharray="4 3"
              opacity={dimUnless(phase === 2)} />
        <text x="1092" y="288" fill="#3ddc84" fontSize="9" textAnchor="middle">key_ID</text>

        {/* WireGuard tunnel across the divider (z=5) — Phase 4 active */}
        <line x1="528" y1="220" x2="712" y2="220"
              stroke={hot(phase === 4)} strokeWidth="3.5" />
        {/* Phase 14-C: label was y=206 colliding with WIREGUARD box title (y=220).
            Moved up to y=174 just below Site A/B headings (y=48). */}
        <text x="620" y="174" fill={hot(phase === 4)} fontSize="11"
              textAnchor="middle" opacity={dimUnless(phase === 4)}>
          VPN tunnel (ChaCha20-Poly1305)
        </text>

        {/* ───── Three separated bottom rows (clearly stacked) ───── */}
        {/* Row 1: PQC KEY exchange (pink, y=420-440) */}
        <path d="M 326 420 Q 620 440 896 420" fill="none"
              stroke="#e91e63" strokeWidth="2"
              opacity={dimUnless((mode === "B" || mode === "C") && phase === 3)} />
        <text x="620" y="436" fill="#e91e63" fontSize="11" textAnchor="middle"
              fontWeight={500}>
          PQC KEY exchange  (Rosenpass A ⇄ B)
        </text>

        {/* Row 2: QKD key_ID exchange (green dashed, y=470-490) */}
        <path d="M 196 470 Q 620 492 1044 470" fill="none"
              stroke="#3ddc84" strokeWidth="1.5" strokeDasharray="5 3"
              opacity={dimUnless(phase === 2)} />
        <text x="620" y="488" fill="#3ddc84" fontSize="11" textAnchor="middle"
              fontWeight={500}>
          QKD key_ID exchange  (ETSI 014)
        </text>

        {/* Row 3: Quantum channel (purple, y=540-560) — clearly at the BOTTOM */}
        <path d="M 75 540 Q 620 590 1165 540" fill="none"
              stroke="#7c5cff" strokeWidth="1.5" strokeDasharray="2 4"
              opacity={dimUnless(phase === 1)} />
        <text x="620" y="558" fill="#7c5cff" fontSize="11" textAnchor="middle"
              fontWeight={500}>
          Quantum Channel  (BB84 photonic)
        </text>

        {/* ───── Bottom-left legend (A/B/C/E) ───── */}
        <g transform="translate(20, 470)">
          <LegendItem y={0}  letter="A" color="#5b8def" text="QKD Mode" />
          <LegendItem y={28} letter="B" color="#5b8def" text="PQC Mode" />
          <LegendItem y={56} letter="C" color="#5b8def" text="Hybrid Mode (QKD+PQC)" />
          <LegendItem y={84} letter="E" color="#f0a020" text="ETSI Interface" />
        </g>
      </svg>
      <div style={{ marginTop: 6, fontSize: 11, color: "#6b7796" }}>
        Active phase: <b style={{ color: "#e25555" }}>{phase || "idle"}</b>
        {" · "}Mode: <b style={{ color: MODE_COLOR[mode] }}>{mode}</b>
      </div>
    </div>
  );
}

function SiteBox({ x, y = 100, label, tag, color, hot }:
                 { x: number; y?: number; label: string; tag: string;
                   color: string; hot: boolean }) {
  const w = 108, h = 80;
  return (
    <g>
      <rect x={x} y={y} width={w} height={h} rx={6}
            fill={`${color}25`} stroke={color}
            strokeWidth={hot ? 2.5 : 1}
            style={{ filter: hot ? `drop-shadow(0 0 8px ${color})` : "none" }} />
      <text x={x + w / 2} y={y + 32} fill={color} fontSize={12}
            textAnchor="middle" fontWeight={700}>
        {label}
      </text>
      <text x={x + w / 2} y={y + 50} fill="#9aa9d8" fontSize={10}
            textAnchor="middle">
        {tag}
      </text>
    </g>
  );
}

function KmsKeystore({ x, active, mirror }:
                     { x: number; active: boolean; mirror?: boolean }) {
  // KMS Keystore [ETSI 014] with QKD sub-box. x is left edge.
  const w = 100, h = 110;
  const cx = x + w / 2;
  return (
    <g style={{ filter: active ? "drop-shadow(0 0 6px #3ddc84)" : "none" }}
       data-mirror={String(!!mirror)}>
      <rect x={x} y={195} width={w} height={h} rx={6}
            fill="#0f3326" stroke="#3ddc84"
            strokeWidth={active ? 2 : 1} />
      <text x={cx} y={222} fill="#c4f5d8" fontSize={12} textAnchor="middle"
            fontWeight={700}>KMS</text>
      <text x={cx} y={240} fill="#c4f5d8" fontSize={11} textAnchor="middle">
        Keystore
      </text>
      <text x={cx} y={256} fill="#c4f5d8" fontSize={10} textAnchor="middle">
        [ETSI 014]
      </text>
      {/* QKD sub-box */}
      <rect x={x + 18} y={272} width={w - 36} height={26} rx={3}
            fill="#1a4332" stroke="#3ddc84" />
      <text x={cx} y={290} fill="#84c89c" fontSize={11} textAnchor="middle">
        QKD
      </text>
    </g>
  );
}

function ETSIBadge({ x, y, active }: { x: number; y: number; active: boolean }) {
  return (
    <g style={{ filter: active ? "drop-shadow(0 0 4px #f0a020)" : "none" }}>
      <circle cx={x} cy={y} r="11" fill="#f0a020"
              opacity={active ? 1 : 0.55} />
      <text x={x} y={y + 4} fill="#fff" fontSize={11} textAnchor="middle"
            fontWeight={700}>E</text>
    </g>
  );
}

function HkdfBadge({ x, y, active }: { x: number; y: number; active: boolean }) {
  return (
    <g style={{ filter: active ? "drop-shadow(0 0 6px #e25555)" : "none" }}>
      <circle cx={x} cy={y} r="14" fill="#e25555"
              opacity={active ? 1 : 0.3} />
      <text x={x} y={y - 2} fill="#fff" fontSize={9} textAnchor="middle"
            fontWeight={700}>HKDF</text>
      <text x={x} y={y + 8} fill="#fff" fontSize={9} textAnchor="middle">SHA3</text>
    </g>
  );
}

function KeyLegend({ x, flip, mode }:
                   { x: number; flip: boolean; mode: string }) {
  // Three key icons (A=QKD orange, B=PQC pink, C=Hybrid red) above each site.
  const items: { letter: string; color: string; label: string; active: boolean }[] = [
    { letter: "C", color: "#e25555", label: "QKD+PQC KEY",
      active: mode === "C" },
    { letter: "B", color: "#e91e63", label: "PQC KEY",
      active: mode === "B" || mode === "C" },
    { letter: "A", color: "#f0a020", label: "QKD KEY",
      active: mode === "A" || mode === "C" },
  ];
  const order = flip ? items.slice().reverse() : items;
  return (
    <g transform={`translate(${x}, 100)`}>
      {order.map((it, i) => {
        const ix = (i - 1) * 80;
        return (
          <g key={it.letter} transform={`translate(${ix}, 0)`}>
            {/* key icon (simple stylised key shape) */}
            <circle cx={0} cy={0} r="8" fill={it.color}
                    opacity={it.active ? 1 : 0.4} />
            <rect x={6} y={-2} width={14} height={4} fill={it.color}
                  opacity={it.active ? 1 : 0.4} />
            {/* letter label */}
            <circle cx={0} cy={26} r="9" fill="#5b8def"
                    opacity={it.active ? 1 : 0.5} />
            <text x={0} y={30} fill="#fff" fontSize={11} textAnchor="middle"
                  fontWeight={700}>{it.letter}</text>
            <text x={0} y={48} fill={it.color} fontSize={9}
                  textAnchor="middle">{it.label}</text>
          </g>
        );
      })}
    </g>
  );
}

function LegendItem({ y, letter, color, text }:
                    { y: number; letter: string; color: string; text: string }) {
  return (
    <g transform={`translate(0, ${y})`}>
      <circle cx={10} cy={10} r="11" fill={color} />
      <text x={10} y={14} fill="#fff" fontSize={12} textAnchor="middle"
            fontWeight={700}>{letter}</text>
      <text x={28} y={14} fill="#9aa9d8" fontSize={11}>{text}</text>
    </g>
  );
}

function KPI({ label, value }: { label: string; value: any }) {
  return (
    <div style={{ background: "#0d1320", border: "1px solid #1d2741",
                   borderRadius: 8, padding: 12 }}>
      <div style={{ fontSize: 11, color: "#6b7796", marginBottom: 4 }}>{label}</div>
      <div style={{ fontSize: 22, color: "#d8e1ff", fontWeight: 700,
                     fontFamily: "monospace" }}>{value}</div>
    </div>
  );
}

function Panel({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div style={{ background: "#0d1320", border: "1px solid #1d2741",
                   borderRadius: 8, padding: 12, marginTop: 8 }}>
      <h3 style={{ margin: "0 0 8px 0", fontSize: 13, color: "#9aa9d8" }}>{title}</h3>
      {children}
    </div>
  );
}

function Row({ k, v }: { k: string; v: any }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between",
                   padding: "3px 0", fontSize: 12, fontFamily: "monospace" }}>
      <span style={{ color: "#9aa9d8" }}>{k}</span>
      <span style={{ color: "#d8e1ff" }}>{String(v)}</span>
    </div>
  );
}

function Badge({ text, color }: { text: string; color: string }) {
  return (
    <span style={{ display: "inline-flex", alignItems: "center",
                    padding: "4px 10px", borderRadius: 12,
                    background: color, color: "#fff", fontSize: 11,
                    marginLeft: "auto" }}>{text}</span>
  );
}

const primaryBtn = (bg: string): React.CSSProperties => ({
  background: bg, color: "#fff", border: "none",
  borderRadius: 4, padding: "6px 14px", fontSize: 13, cursor: "pointer",
  fontWeight: 600,
});

const modeBtn = (active: boolean, color: string): React.CSSProperties => ({
  background: active ? color : "#0d1320", color: active ? "#fff" : color,
  border: `1px solid ${color}`, borderRadius: 4,
  padding: "4px 12px", fontSize: 12, cursor: "pointer",
  fontWeight: active ? 700 : 500,
});
