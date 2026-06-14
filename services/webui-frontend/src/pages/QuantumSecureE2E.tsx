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
        <ArchLegend />
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

// ── Architecture diagram geometry (single source of truth) ──────────────
// All coordinates derive from GEO so labels/arrows can't drift. Site B is the
// exact mirror of Site A about the centre divider, giving symmetric gaps.
const GEO = {
  W: 1240, H: 600, divider: 620,
  box: { w: 108, h: 80, y: 200 },          // ARNIKA / ROSENPASS / WIREGUARD
  kms: { w: 100, h: 110, y: 195, lx: 40 }, // left KMS (right is mirrored)
  // Site A left-edge x's (Site B mirrored: xB = W - x - box.w)
  a: { arnika: 196, rosenpass: 326, wireguard: 456 },
};
const mirrorX = (x: number, w: number) => GEO.W - x - w;
const GA = GEO.a;
const GB = {
  wireguard: mirrorX(GA.wireguard, GEO.box.w), // 676
  rosenpass: mirrorX(GA.rosenpass, GEO.box.w), // 806
  arnika:    mirrorX(GA.arnika, GEO.box.w),    // 936
};
const kmsRx = mirrorX(GEO.kms.lx, GEO.kms.w);  // 1100
// Box edge helpers (snap arrows/badges to real rectangle edges)
const boxMidY = GEO.box.y + GEO.box.h / 2;          // 240
const rightEdge = (x: number) => x + GEO.box.w;
const kmsRightEdge = GEO.kms.lx + GEO.kms.w;        // 140
// Vertical bands for the three stacked bottom exchange lanes
const LANE = { pqc: 422, qkd: 472, quantum: 524 };

function ArchSvg({ mode, phase }: { mode: string; phase: number }) {
  // Highlight rules:
  //   mode "A" (QKD-only) -> orange path active in phase 1-2
  //   mode "B" (PQC-only) -> pink path active in phase 3
  //   mode "C" (Hybrid)   -> red HKDF box active in phase 3, tunnel in phase 4
  //
  // Layout v3 (Round 3): geometry-driven 1240×600 viewBox. Site B mirrors
  // Site A about the divider so KMS↔ARNIKA gaps are symmetric; every arrow
  // starts/ends on a computed box edge; the A/B/C/E mode legend moved OUT of
  // the SVG to an HTML strip (ArchLegend) — it used to duplicate the top key
  // legend and collide with the bottom exchange-lane arcs.
  const hot = (cond: boolean) =>
    cond ? "#e25555" : "#3a4a78";
  const dimUnless = (cond: boolean) => (cond ? 1 : 0.3);
  return (
    <div style={{ background: "#0d1320", border: "1px solid #1d2741",
                   borderRadius: 8, padding: 12, marginBottom: 10 }}>
      <svg id="e2e-arch-svg" viewBox={`0 0 ${GEO.W} ${GEO.H}`} style={{ width: "100%" }}
           role="img" aria-label="Quantum-secure VPN architecture (Image 1 faithful)">
        {/* ───── Dashed boundary boxes (z=0, back) ───── */}
        {/* Quantum Key Distribution Infrastructure (left + right, blue) */}
        <rect x="10" y="110" width="130" height="380" rx="6"
              fill="none" stroke="#5b8def" strokeWidth="1.5" strokeDasharray="5 4" />
        <text x="75" y="130" fill="#5b8def" fontSize="11" textAnchor="middle">Quantum Key</text>
        <text x="75" y="144" fill="#5b8def" fontSize="11" textAnchor="middle">Distribution</text>
        <text x="75" y="158" fill="#5b8def" fontSize="11" textAnchor="middle">Infrastructure</text>

        <rect x="1100" y="110" width="130" height="380" rx="6"
              fill="none" stroke="#5b8def" strokeWidth="1.5" strokeDasharray="5 4" />
        <text x="1165" y="130" fill="#5b8def" fontSize="11" textAnchor="middle">Quantum Key</text>
        <text x="1165" y="144" fill="#5b8def" fontSize="11" textAnchor="middle">Distribution</text>
        <text x="1165" y="158" fill="#5b8def" fontSize="11" textAnchor="middle">Infrastructure</text>

        {/* VPN scope (red dashed, mid-large) */}
        <rect x="150" y="64" width="940" height="450" rx="8"
              fill="none" stroke="#e25555" strokeWidth="1.5" strokeDasharray="6 4" />
        <text x="620" y="82" fill="#e25555" fontSize="13" textAnchor="middle"
              fontStyle="italic">VPN scope</text>

        {/* Secure Application Entity (purple dashed, inside VPN scope per-site) */}
        <rect x="180" y="170" width="412" height="198" rx="6"
              fill="none" stroke="#7c5cff" strokeWidth="1.4" strokeDasharray="5 3" />
        <text x="386" y="360" fill="#7c5cff" fontSize="11" textAnchor="middle">
          Secure Application Entity
        </text>
        <rect x="648" y="170" width="412" height="198" rx="6"
              fill="none" stroke="#7c5cff" strokeWidth="1.4" strokeDasharray="5 3" />
        <text x="854" y="360" fill="#7c5cff" fontSize="11" textAnchor="middle">
          Secure Application Entity
        </text>

        {/* ───── Center divider + VPN lock (z=1) ───── */}
        <line x1={GEO.divider} y1="54" x2={GEO.divider} y2="500" stroke="#3a4a78"
              strokeWidth="1.5" strokeDasharray="6 5" />
        <text x="260" y="50" fill="#cbd6f5" fontSize="14" textAnchor="middle"
              fontWeight={700}>Site A</text>
        <text x="980" y="50" fill="#cbd6f5" fontSize="14" textAnchor="middle"
              fontWeight={700}>Site B</text>
        {/* VPN lock icon on the tunnel at the centre divider */}
        <g transform={`translate(${GEO.divider},${boxMidY})`}>
          <circle r="14" fill="#e25555" opacity={dimUnless(phase === 4)} />
          <rect x="-7" y="-3" width="14" height="11" rx="1" fill="#fff"
                opacity={dimUnless(phase === 4)} />
          <path d="M -4,-3 L -4,-7 Q -4,-11 0,-11 Q 4,-11 4,-7 L 4,-3"
                stroke="#fff" strokeWidth="1.5" fill="none"
                opacity={dimUnless(phase === 4)} />
          <text y="30" fill="#e25555" fontSize="10" textAnchor="middle"
                fontWeight={700}>VPN</text>
        </g>

        {/* ───── Top key-color legend (A/B/C with key icons), mirrored ───── */}
        <KeyLegend x={280} flip={false} mode={mode} />
        <KeyLegend x={960} flip={true}  mode={mode} />

        {/* ───── KMS keystores (z=2) ───── */}
        <KmsKeystore x={GEO.kms.lx}  active={phase === 2} />
        <KmsKeystore x={kmsRx} active={phase === 2} mirror />

        {/* ───── Site A inner boxes (z=3) ───── */}
        <SiteBox x={GA.arnika} label="ARNIKA" tag="KEY-CONTROL" color="#f0a020"
                 hot={phase === 2 || phase === 3} />
        <SiteBox x={GA.rosenpass} label="ROSENPASS" tag="PQC function" color="#e91e63"
                 hot={(mode === "B" || mode === "C") && phase === 3} />
        <SiteBox x={GA.wireguard} label="WIREGUARD" tag="VPN function" color="#7c5cff"
                 hot={phase === 4} />

        {/* Site B (exact mirror) */}
        <SiteBox x={GB.wireguard} label="WIREGUARD" tag="VPN function" color="#7c5cff"
                 hot={phase === 4} />
        <SiteBox x={GB.rosenpass} label="ROSENPASS" tag="PQC function" color="#e91e63"
                 hot={(mode === "B" || mode === "C") && phase === 3} />
        <SiteBox x={GB.arnika} label="ARNIKA" tag="KEY-CONTROL" color="#f0a020"
                 hot={phase === 2 || phase === 3} />

        {/* HKDF-SHA3 indicator (z=4) — top-inner corner of each ARNIKA box,
            clear of the centred title/tag rows. */}
        <HkdfBadge x={rightEdge(GA.arnika) - 16} y={GEO.box.y + 15}
                   active={mode === "C" && phase === 3} />
        <HkdfBadge x={GB.arnika + 16} y={GEO.box.y + 15}
                   active={mode === "C" && phase === 3} />

        {/* ───── KMS↔ARNIKA ETSI-014 interface (z=5) ─────
            Two arrows in the symmetric 56 px gap: QKD KEY (KMS→ARNIKA) above,
            key_ID (ARNIKA→KMS) below, the "E" interface badge between them.
            Labels sit in the clear bands above/below the box row. */}
        {/* Left site */}
        <ArrowX x1={kmsRightEdge} x2={GA.arnika} y={boxMidY - 14} color="#f0a020"
                width={2} active={phase === 2} headAt="end" />
        <text x={(kmsRightEdge + GA.arnika) / 2} y={GEO.box.y - 8} fill="#f0a020"
              fontSize="9" textAnchor="middle">QKD KEY</text>
        <ArrowX x1={GA.arnika} x2={kmsRightEdge} y={boxMidY + 14} color="#3ddc84"
                width={1.5} dashed active={phase === 2} headAt="end" />
        <text x={(kmsRightEdge + GA.arnika) / 2} y={GEO.box.y + GEO.box.h + 16}
              fill="#3ddc84" fontSize="9" textAnchor="middle">key_ID</text>
        <ETSIBadge x={(kmsRightEdge + GA.arnika) / 2} y={boxMidY} active={phase === 2} />
        {/* Right site (mirror) */}
        <ArrowX x1={kmsRx} x2={rightEdge(GB.arnika)} y={boxMidY - 14} color="#f0a020"
                width={2} active={phase === 2} headAt="end" />
        <text x={(kmsRx + rightEdge(GB.arnika)) / 2} y={GEO.box.y - 8} fill="#f0a020"
              fontSize="9" textAnchor="middle">QKD KEY</text>
        <ArrowX x1={rightEdge(GB.arnika)} x2={kmsRx} y={boxMidY + 14} color="#3ddc84"
                width={1.5} dashed active={phase === 2} headAt="end" />
        <text x={(kmsRx + rightEdge(GB.arnika)) / 2} y={GEO.box.y + GEO.box.h + 16}
              fill="#3ddc84" fontSize="9" textAnchor="middle">key_ID</text>
        <ETSIBadge x={(kmsRx + rightEdge(GB.arnika)) / 2} y={boxMidY} active={phase === 2} />

        {/* WireGuard tunnel across the divider (z=5) — snapped to WG box edges */}
        <line x1={rightEdge(GA.wireguard)} y1={boxMidY} x2={GB.wireguard} y2={boxMidY}
              stroke={hot(phase === 4)} strokeWidth="3.5" />
        <text x={GEO.divider} y={GEO.box.y - 8} fill={hot(phase === 4)} fontSize="11"
              textAnchor="middle" opacity={dimUnless(phase === 4)}>
          VPN tunnel (ChaCha20-Poly1305)
        </text>

        {/* ───── Three separated bottom exchange lanes (clearly stacked) ───── */}
        {/* Lane 1: PQC KEY exchange (pink) — ROSENPASS A ⇄ B */}
        <text x={GEO.divider} y={LANE.pqc - 10} fill="#e91e63" fontSize="11"
              textAnchor="middle" fontWeight={500}>
          PQC KEY exchange  (Rosenpass A ⇄ B)
        </text>
        <path d={`M ${GA.rosenpass + GEO.box.w / 2} ${LANE.pqc} Q ${GEO.divider} ${LANE.pqc + 22} ${GB.rosenpass + GEO.box.w / 2} ${LANE.pqc}`}
              fill="none" stroke="#e91e63" strokeWidth="2"
              opacity={dimUnless((mode === "B" || mode === "C") && phase === 3)} />

        {/* Lane 2: QKD key_ID exchange (green dashed) — ARNIKA A ⇄ B */}
        <text x={GEO.divider} y={LANE.qkd - 10} fill="#3ddc84" fontSize="11"
              textAnchor="middle" fontWeight={500}>
          QKD key_ID exchange  (ETSI 014)
        </text>
        <path d={`M ${GA.arnika + GEO.box.w / 2} ${LANE.qkd} Q ${GEO.divider} ${LANE.qkd + 22} ${GB.arnika + GEO.box.w / 2} ${LANE.qkd}`}
              fill="none" stroke="#3ddc84" strokeWidth="1.5" strokeDasharray="5 3"
              opacity={dimUnless(phase === 2)} />

        {/* Lane 3: Quantum channel (purple) — infra ⇄ infra, at the very bottom */}
        <text x={GEO.divider} y={LANE.quantum - 10} fill="#7c5cff" fontSize="11"
              textAnchor="middle" fontWeight={500}>
          Quantum Channel  (BB84 photonic)
        </text>
        <path d={`M 75 ${LANE.quantum} Q ${GEO.divider} ${LANE.quantum + 28} 1165 ${LANE.quantum}`}
              fill="none" stroke="#7c5cff" strokeWidth="1.5" strokeDasharray="2 4"
              opacity={dimUnless(phase === 1)} />
      </svg>
      <div style={{ marginTop: 6, fontSize: 11, color: "#6b7796" }}>
        Active phase: <b style={{ color: "#e25555" }}>{phase || "idle"}</b>
        {" · "}Mode: <b style={{ color: MODE_COLOR[mode] }}>{mode}</b>
      </div>
    </div>
  );
}

// Horizontal arrow snapped to two x coordinates with an optional arrowhead.
function ArrowX({ x1, x2, y, color, width, dashed, active, headAt }:
                { x1: number; x2: number; y: number; color: string;
                  width: number; dashed?: boolean; active: boolean;
                  headAt: "start" | "end" }) {
  const dir = x2 > x1 ? 1 : -1;
  const hx = headAt === "end" ? x2 : x1;
  const hd = headAt === "end" ? dir : -dir;
  return (
    <g opacity={active ? 1 : 0.3}>
      <line x1={x1} y1={y} x2={x2} y2={y} stroke={color} strokeWidth={width}
            strokeDasharray={dashed ? "4 3" : undefined} />
      <path d={`M ${hx} ${y} l ${-6 * hd} ${-4} l 0 8 z`} fill={color} />
    </g>
  );
}

// HTML legend strip below the SVG (replaces the in-SVG A/B/C/E legend that
// duplicated the top key legend and collided with the bottom lanes).
function ArchLegend() {
  const items = [
    { letter: "A", color: "#f0a020", text: "QKD Mode" },
    { letter: "B", color: "#e91e63", text: "PQC Mode" },
    { letter: "C", color: "#e25555", text: "Hybrid Mode (QKD ‖ PQC)" },
    { letter: "E", color: "#f0a020", text: "ETSI 014 Interface" },
  ];
  return (
    <div style={{ display: "flex", gap: 18, flexWrap: "wrap", alignItems: "center",
                   marginBottom: 10, padding: "8px 12px", background: "#0d1320",
                   border: "1px solid #1d2741", borderRadius: 8 }}>
      {items.map((it) => (
        <span key={it.letter} style={{ display: "inline-flex", alignItems: "center",
                                        gap: 6, fontSize: 12, color: "#9aa9d8" }}>
          <span style={{ display: "inline-flex", alignItems: "center",
                          justifyContent: "center", width: 20, height: 20,
                          borderRadius: "50%", background: it.color, color: "#fff",
                          fontSize: 11, fontWeight: 700 }}>{it.letter}</span>
          {it.text}
        </span>
      ))}
    </div>
  );
}

function SiteBox({ x, y = GEO.box.y, label, tag, color, hot }:
                 { x: number; y?: number; label: string; tag: string;
                   color: string; hot: boolean }) {
  const w = GEO.box.w, h = GEO.box.h;
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
      <circle cx={x} cy={y} r="15" fill="#e25555"
              opacity={active ? 1 : 0.3} />
      <text x={x} y={y - 3} fill="#fff" fontSize={8} textAnchor="middle"
            fontWeight={700}>HKDF</text>
      <text x={x} y={y + 8} fill="#fff" fontSize={8} textAnchor="middle">SHA3</text>
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
