/**
 * Multi-hop trusted-node topology SVG (Phase 14).
 *
 * Faithful to the Veriqloud/arnika-vq image:
 *   End Node Alice | Trusted Node × N | End Node Bob
 *
 * Each column stacks: QKD Device → KMS Keystore (ETSI 014) → Arnika → VPN
 * WireGuard. End-node columns also carry PQC Rosenpass and a DATA IPv4/IPv6
 * box at the bottom. Numbered phase markers (① Quantum Plane / ② QKD Key
 * IDs / ③ PQC Handshake / ④ Data Exchange) highlight per the live
 * orchestrator phase prop.
 */
import { colors } from "../lib/commonStyles";

export interface MultiHopTopologyProps {
  hopCount: number;       // number of Trusted Nodes between Alice and Bob
  currentPhase: number;   // 0=idle, 1..5
  failureLayer?: string | null;
}

export default function MultiHopTopologySvg({
  hopCount, currentPhase, failureLayer,
}: MultiHopTopologyProps) {
  const tnCount = Math.max(0, Math.min(8, hopCount));
  // Build columns: [Alice, TN1, TN2, ..., TNn, Bob]
  const cols: { label: string; isEnd: boolean }[] = [
    { label: "End Node Alice", isEnd: true },
    ...Array.from({ length: tnCount }, (_, i) => ({
      label: `Trusted Node ${i + 1}`, isEnd: false,
    })),
    { label: "End Node Bob", isEnd: true },
  ];

  const colW = 150;
  const colGap = 20;
  // Wider left gutter hosts the phase legend so its labels never overlap the
  // first Trusted-Node column (previous bug: title text rendered at x=cx+20
  // landed inside the TN1 column).
  const padL = 168;
  const padR = 30;
  const W = padL + padR + cols.length * colW + (cols.length - 1) * colGap;
  const H = 720;

  // Phase highlight helpers (return CSS filter for active glow)
  const glow = (active: boolean, hex: string) =>
    active && currentPhase > 0 ? `drop-shadow(0 0 6px ${hex})` : "none";
  const dimUnless = (active: boolean) => (active ? 1 : 0.4);
  const phaseColor: Record<number, string> = {
    1: colors.vpn,         // purple
    2: colors.qkd,         // orange
    3: colors.pqc,         // pink (PQC handshake)
    4: colors.danger,      // red (final data exchange)
  };

  // Injected-failure highlight: outline the affected layer's box(es) red so the
  // failure is visually unambiguous (not just the bottom banner).
  const failed = (layer: string) => failureLayer === layer;
  const failStroke = (layer: string, base: string) =>
    failed(layer) ? colors.danger : base;
  const failWidth = (layer: string) => (failed(layer) ? 2.5 : 1);
  const failGlow = (layer: string, phaseGlow: string) =>
    failed(layer) ? `drop-shadow(0 0 7px ${colors.danger})` : phaseGlow;

  return (
    <svg id="paper-flow-topology-svg" viewBox={`0 0 ${W} ${H}`}
         style={{ width: "100%" }}
         role="img"
         aria-label="Multi-hop trusted-node topology (Spooren et al. arXiv:2604.05599)">
      {/* Background columns */}
      {cols.map((c, i) => {
        const x = padL + i * (colW + colGap);
        const stripe = c.isEnd ? "#0d1320" : "#0f1830";
        return (
          <g key={i}>
            <rect x={x} y={20} width={colW} height={H - 40}
                  fill={stripe} stroke={colors.border}
                  strokeDasharray={c.isEnd ? "0" : "5 4"} rx={8} />
            <text x={x + colW / 2} y={42} fill={colors.textPri}
                  fontSize={13} fontWeight={700} textAnchor="middle">
              {c.label}
            </text>
          </g>
        );
      })}

      {/* Phase legend (left gutter) — numbered markers + titles, clear of all
          columns. Highlights the active phase. */}
      <text x={24} y={42} fill={colors.textMute} fontSize={11} fontWeight={700}>
        Phases
      </text>
      {[
        { idx: 1, label: "①", title: "Quantum Plane" },
        { idx: 2, label: "②", title: "QKD Key IDs" },
        { idx: 3, label: "③", title: "PQC Handshake" },
        { idx: 4, label: "④", title: "Data Exchange" },
      ].map(({ idx, label, title }) => {
        const cx = 26;
        const cy = 80 + (idx - 1) * 44;
        const active = currentPhase === idx;
        return (
          <g key={idx} transform={`translate(${cx}, ${cy})`}>
            <circle r={12} fill={active ? phaseColor[idx] : colors.panelBg}
                    stroke={phaseColor[idx]} strokeWidth={active ? 2.5 : 1.5}
                    style={{ filter: glow(active, phaseColor[idx]) }} />
            <text textAnchor="middle" dy={4} fill={active ? "#fff" : phaseColor[idx]}
                  fontSize={11} fontWeight={700}>{label}</text>
            <text x={20} y={4} fill={phaseColor[idx]} fontSize={10}
                  opacity={dimUnless(active)}>{title}</text>
          </g>
        );
      })}

      {/* Stack rows: each column gets boxes for QKD Device, KMS, Arnika, WG, Rosenpass (if end), Data (if end) */}
      {cols.map((c, i) => {
        const x = padL + i * (colW + colGap);
        const boxX = x + 18;
        const boxW = colW - 36;
        const phase2Active = currentPhase === 2;
        const phase3Active = currentPhase === 3;
        const phase4Active = currentPhase === 4 || currentPhase === 5;

        return (
          <g key={`stack-${i}`}>
            {/* QKD Device */}
            <rect x={boxX} y={70} width={boxW} height={50} rx={5}
                  fill={"#0f3326"} stroke={failStroke("qkd", colors.success)}
                  strokeWidth={failWidth("qkd")}
                  style={{ filter: failGlow("qkd", glow(currentPhase === 1, colors.success)) }} />
            <text x={boxX + boxW / 2} y={92} fill={colors.success}
                  fontSize={12} textAnchor="middle" fontWeight={700}>QKD Device</text>
            <text x={boxX + boxW / 2} y={108} fill={colors.success}
                  fontSize={10} textAnchor="middle">(physical)</text>

            {/* KMS Keystore [ETSI 014] */}
            <rect x={boxX} y={140} width={boxW} height={60} rx={5}
                  fill={"#0f3326"} stroke={failStroke("qkd", colors.success)}
                  strokeWidth={failWidth("qkd")}
                  style={{ filter: failGlow("qkd", glow(phase2Active, colors.success)) }} />
            <text x={boxX + boxW / 2} y={162} fill={colors.success}
                  fontSize={11} textAnchor="middle" fontWeight={700}>KMS Keystore</text>
            <text x={boxX + boxW / 2} y={178} fill={colors.success}
                  fontSize={10} textAnchor="middle">[ETSI 014]</text>
            <text x={boxX + boxW / 2} y={193} fill={colors.success}
                  fontSize={9} textAnchor="middle">QKD key store</text>

            {/* Arnika */}
            <rect x={boxX} y={230} width={boxW} height={50} rx={5}
                  fill={`${colors.qkd}25`} stroke={failStroke("arnika", colors.qkd)}
                  strokeWidth={failWidth("arnika")}
                  style={{ filter: failGlow("arnika", glow(phase2Active, colors.qkd)) }} />
            <text x={boxX + boxW / 2} y={252} fill={colors.qkd}
                  fontSize={12} textAnchor="middle" fontWeight={700}>Arnika</text>
            <text x={boxX + boxW / 2} y={268} fill={colors.qkd}
                  fontSize={10} textAnchor="middle">KEY-CONTROL</text>

            {/* WireGuard VPN */}
            <rect x={boxX} y={320} width={boxW} height={50} rx={5}
                  fill={`${colors.vpn}25`} stroke={failStroke("wireguard", colors.vpn)}
                  strokeWidth={failWidth("wireguard")}
                  style={{ filter: failGlow("wireguard", glow(phase3Active || phase4Active, colors.vpn)) }} />
            <text x={boxX + boxW / 2} y={342} fill={colors.vpn}
                  fontSize={12} textAnchor="middle" fontWeight={700}>VPN WireGuard</text>
            <text x={boxX + boxW / 2} y={358} fill={colors.vpn}
                  fontSize={10} textAnchor="middle">hop tunnel</text>

            {/* Only end nodes get Rosenpass + DATA */}
            {c.isEnd && (
              <>
                <rect x={boxX} y={410} width={boxW} height={50} rx={5}
                      fill={`${colors.pqc}25`} stroke={failStroke("rosenpass", colors.pqc)}
                      strokeWidth={failWidth("rosenpass")}
                      style={{ filter: failGlow("rosenpass", glow(phase3Active, colors.pqc)) }} />
                <text x={boxX + boxW / 2} y={432} fill={colors.pqc}
                      fontSize={12} textAnchor="middle" fontWeight={700}>PQC Rosenpass</text>
                <text x={boxX + boxW / 2} y={448} fill={colors.pqc}
                      fontSize={10} textAnchor="middle">end-to-end</text>

                <rect x={boxX} y={490} width={boxW} height={50} rx={5}
                      fill={`${colors.danger}20`} stroke={colors.danger}
                      strokeWidth={failWidth("data")}
                      style={{ filter: failGlow("data", glow(phase4Active, colors.danger)) }} />
                <text x={boxX + boxW / 2} y={512} fill={colors.danger}
                      fontSize={12} textAnchor="middle" fontWeight={700}>Final WG tunnel</text>
                <text x={boxX + boxW / 2} y={528} fill={colors.danger}
                      fontSize={10} textAnchor="middle">ChaCha20-Poly1305</text>

                <rect x={boxX} y={570} width={boxW} height={40} rx={5}
                      fill="#1a2440" stroke={failStroke("data", colors.borderLt)}
                      strokeWidth={failWidth("data")}
                      style={{ filter: failGlow("data", "none") }} />
                <text x={boxX + boxW / 2} y={596} fill={colors.textPri}
                      fontSize={11} textAnchor="middle">DATA IPv4 / IPv6</text>
              </>
            )}
          </g>
        );
      })}

      {/* Inter-column connectors per phase */}
      {cols.slice(0, -1).map((_, i) => {
        const xL = padL + i * (colW + colGap) + colW - 18;
        const xR = padL + (i + 1) * (colW + colGap) + 18;
        const phase1Active = currentPhase === 1;
        const phase2Active = currentPhase === 2;
        const phase3Active = currentPhase === 3;
        const phase4Active = currentPhase === 4 || currentPhase === 5;
        return (
          <g key={`conn-${i}`}>
            {/* ① QKD Device ↔ QKD Device (Quantum Plane, dashed purple) */}
            <line x1={xL} y1={95} x2={xR} y2={95}
                  stroke={colors.vpn} strokeWidth={2} strokeDasharray="4 4"
                  opacity={dimUnless(phase1Active)} />
            {/* ② Arnika ↔ Arnika (orange dashed key_ID exchange) */}
            <line x1={xL} y1={255} x2={xR} y2={255}
                  stroke={colors.qkd} strokeWidth={2} strokeDasharray="6 3"
                  opacity={dimUnless(phase2Active)} />
            {/* ③ WG ↔ WG hop tunnel (solid pink/magenta) */}
            <line x1={xL} y1={345} x2={xR} y2={345}
                  stroke={colors.pqc} strokeWidth={2.5}
                  opacity={dimUnless(phase3Active)} />
          </g>
        );
      })}

      {/* End-to-end PQC handshake (Rosenpass overlay) — arc joining the TOP EDGE
          midpoint of Alice's and Bob's Rosenpass boxes (box top y=410, not the
          box centre); it bows up to apex 388 so it visibly rises from the edge. */}
      {(() => {
        const aliceCx = padL + 18 + (colW - 36) / 2;
        const bobCx = padL + (cols.length - 1) * (colW + colGap) + 18 + (colW - 36) / 2;
        const rpTop = 410;            // Rosenpass box top edge (box is y=410 h=50)
        const phase3Active = currentPhase === 3;
        const midX = (aliceCx + bobCx) / 2;
        return (
          <g opacity={dimUnless(phase3Active)}>
            <path d={`M ${aliceCx} ${rpTop} Q ${midX} 388 ${bobCx} ${rpTop}`}
                  fill="none" stroke={colors.pqc} strokeWidth={2.5} />
            <circle cx={aliceCx} cy={rpTop} r={3} fill={colors.pqc} />
            <circle cx={bobCx} cy={rpTop} r={3} fill={colors.pqc} />
            <text x={midX} y={381} fill={colors.pqc} fontSize={11}
                  textAnchor="middle">
              ③ PQC Handshake (Rosenpass end-to-end)
            </text>
          </g>
        );
      })()}

      {/* Final data tunnel — joins the SIDE EDGES of the end-node Final-WG boxes
          (Alice box right edge → Bob box left edge) at the box mid-height (515),
          not through the box centres. */}
      {(() => {
        const aliceRight = padL + 18 + (colW - 36);                         // Alice box right edge
        const bobLeft = padL + (cols.length - 1) * (colW + colGap) + 18;    // Bob box left edge
        const yMid = 515;          // Final-WG box mid (box is y=490 h=50)
        const phase4Active = currentPhase === 4 || currentPhase === 5;
        const midX = (aliceRight + bobLeft) / 2;
        return (
          <g opacity={dimUnless(phase4Active)}>
            <line x1={aliceRight} y1={yMid} x2={bobLeft} y2={yMid}
                  stroke={colors.danger} strokeWidth={3} />
            <circle cx={aliceRight} cy={yMid} r={3} fill={colors.danger} />
            <circle cx={bobLeft} cy={yMid} r={3} fill={colors.danger} />
            <text x={midX} y={508} fill={colors.danger} fontSize={11}
                  textAnchor="middle" fontWeight={600}>
              ④ Data Exchange (ChaCha20-Poly1305)
            </text>
          </g>
        );
      })()}

      {/* Failure layer banner */}
      {failureLayer && (
        <g>
          <rect x={W / 2 - 200} y={H - 28} width={400} height={20} rx={4}
                fill={colors.danger} opacity={0.85} />
          <text x={W / 2} y={H - 14} fill="#fff" fontSize={11}
                textAnchor="middle" fontWeight={700}>
            ⚠ Failure injected on layer: {failureLayer}
          </text>
        </g>
      )}
    </svg>
  );
}
