import { useState } from "react";
import { Link } from "react-router-dom";
import { getStack, postStack, type StackItem } from "../api";
import { usePoll } from "../lib/usePoll";
import { useRuntimeConfig } from "../lib/useConfig";

/** Matches the backend's STACK_TTL_S, so a viewer does not outpace its cache. */
const STACK_POLL_MS = 3000;
import PageHeader from "../components/PageHeader";
import ExportToolbar from "../components/ExportToolbar";
import ScrollRegion from "../components/ScrollRegion";
import { useContainerControl } from "../lib/useConfig";
import { narrowColumns, useNarrowLayout } from "../lib/layout";

/**
 * The two-column grid of this page: the layer diagram beside the container
 * table. Below the shell's breakpoint (lib/layout.ts) it is one column.
 *
 * Measured on 2026-09-26 with the collapsed shell: at a 375px viewport the two
 * `1fr` tracks could not shrink below their content (a bare `1fr` has an
 * `auto` minimum), so they came to 200px + 182px in a 343px row and the page
 * scrolled sideways by 39px; at 320px, by 94px. The container table's Status
 * column and the "Container Status" heading were what stuck out.
 */
const OVERVIEW_WIDE_COLUMNS = "1fr 1fr";

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
      // "not deployed here", not "not started": whether a profile runs is a
      // per-host deployment choice, and "not started" read as a start someone
      // forgot. The explanation is also printed under the table -- a tooltip
      // is invisible on touch screens and often skipped by screen readers.
      label: `not deployed here (${s.profile})`,
      color: "#3a4a6b",
      title: s.note,
    };
  }
  // The backend's note begins "Absent here means..." and was attached to the
  // green `running` chips of alice-ipsec and bob-ipsec too, where it
  // contradicted the chip. A running optional row gets its provenance only.
  const title = s.optional && s.compose_file
    ? `defined in ${s.compose_file} (profile ${s.profile})` : undefined;
  return { label: s.status, color: STATUS_COLOR[s.status] || "#445", title };
}

/**
 * What a profile-gated service IS, for the visible note under the table. Only
 * services whose absence needs explaining are listed; the backend supplies the
 * compose file and profile, this adds the one sentence it cannot.
 */
const OPTIONAL_ROLE: Record<string, string> = {
  "qkdnetsim-kme":
    "a Flask facade that serves ETSI GS QKD 014 keys for cross-validation; the NS-3 "
    + "simulator is built into its image but not run",
};

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
  const runtime = useRuntimeConfig();
  const narrow = useNarrowLayout();
  const [actionError, setActionError] = useState<string>("");

  // Why the status table is empty, when it is. The page had no failure path:
  // a failed /api/stack left the previous table (or nothing) with no sign that
  // it had stopped updating.
  const [stackErr, setStackErr] = useState<string>("");
  async function refresh() {
    try { setStack(await getStack()); setStackErr(""); }
    catch (e) { setStackErr(e instanceof Error ? e.message : String(e)); }
  }
  usePoll(refresh, STACK_POLL_MS);

  return (
    <div>
      <PageHeader
        title="Architecture & Live Status"
        subtitle={<>Three key sources feed two VPN lanes. (1) <code>bb84-kme</code> delivers
          QKD keys over ETSI 014. (2) <code>arnika</code> agrees a PQC key with its peer by
          PQC-HPKE and fuses it with the QKD key through HKDF-SHA3-256. (3) Rosenpass runs its
          own exchange through the WireGuard hop tunnel and keys a second tunnel inside it.
          {" "}<b>WireGuard lane:</b> wg0 hop tunnel keyed by arnika (HKDF-SHA3-256 over the
          QKD key and a PQC-HPKE key) + wg1 data tunnel keyed by Rosenpass (Classic McEliece
          460896 + Kyber512). Both keys are WireGuard preshared keys, which enter the
          Noise_IKpsk2 chaining key, and wg1&apos;s peer endpoint is the peer&apos;s wg0
          address, so every wg1 packet also travels inside wg0.
          {" "}<b>IPsec lane</b> (<code>alice-ipsec</code>/<code>bob-ipsec</code>, with its own
          arnika pair and no Rosenpass): IKEv2 with ML-KEM-768 (RFC 9370) + RFC 8784 PPK =
          arnika HKDF-SHA3-256(QKD || PQC-HPKE), installed over strongSwan&rsquo;s VICI
          socket; see <Link to="/vpn">VPN Protocols</Link>.
          {" "}PQC-HPKE is HPKE Base mode (RFC 9180) with the KEM MLKEM1024-P384, a hybrid of
          ML-KEM-1024 and P-384 (codepoint 0x0051, from draft-ietf-hpke-pq, not yet an RFC),
          the KDF HKDF-SHA384 and an export-only AEAD. Rotation is configured at{" "}
          <code>{runtime.arnika_interval ?? "(not reported)"}</code> (<code>ARNIKA_INTERVAL</code>), but the interval
          is when arnika <i>attempts</i> a rotation, not a guarantee: gaps measured on the public
          host on 2026-08-23 ran 30&ndash;241 s, so count rotations over a window (the rotations
          panel on <Link to="/vpn">/vpn</Link>) rather than dividing by the interval.</>}
      />
      <div style={{ marginBottom: 12 }}>
        {/* Not animated: the architecture figure is static, so a WebM or GIF
            of it would be ten seconds of one frame. */}
        <ExportToolbar
          name="overview"
          logService="webui-backend"
          pngTargetSelector="#overview-arch-svg"
          jsonProvider={() => ({ stack })}
          animated={false}
        />
      </div>

      <div style={{ display: "grid", gridTemplateColumns: narrowColumns(narrow, OVERVIEW_WIDE_COLUMNS), gap: 16, marginTop: 20 }}>
        <ArchPanel />
        <div>
          <h3>Container Status</h3>
          {stackErr && (
            <p role="status" style={{ color: "#f5a623", fontSize: 12 }}>
              Not observed -- GET /api/stack failed: {stackErr}.
              {stack.length ? " The table below is the last successful reading." : ""}
            </p>
          )}
          {/* A <table> does not scroll itself, so if a long container name
              or chip ever makes it wider than a phone, it scrolls inside this
              box instead of widening the page. While it does, the box is also
              a labelled region the keyboard can reach; while the table fits,
              it is a plain div and no Tab stop (components/ScrollRegion). */}
          <ScrollRegion aria-label="Container status table">
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
          </ScrollRegion>
          {/* The profile comes from the row; nothing here says which profiles
              a deploy script can start. It said "which this host's deploy
              script does not start" for every absent row, and that is false
              for the ipsec profile: deploy/deploy.sh starts alice-ipsec and
              bob-ipsec with --ipsec. What the row does establish is that the
              profile was not started on this host. */}
          {stack.filter((s) => s.optional && s.status === "absent").map((s) => (
            // overflowWrap only when narrow: a compose file name is one
            // unbreakable token, and in a phone-width column it may break
            // rather than stick out. Wider, the note lays out as before.
            <p key={s.name} style={{ fontSize: 11, color: "#9aa9d8", margin: "8px 0 0", lineHeight: 1.5,
                                     overflowWrap: narrow ? "anywhere" : undefined }}>
              <code>{s.name}</code>: not deployed on this host. It is defined only in{" "}
              <code>{s.compose_file ?? "(compose file not reported)"}</code> behind the{" "}
              <code>{s.profile ?? "(profile not reported)"}</code> profile, which was not
              started on this host &mdash; a deployment choice, not a failure and not a
              licensing restriction.{OPTIONAL_ROLE[s.name] ? ` It is ${OPTIONAL_ROLE[s.name]}.` : ""}
            </p>
          ))}
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

/**
 * Box geometry for the layer diagram, in viewBox units. Named so the arrows
 * can be derived from the boxes they join (checklist 4.2.6: a connector ends
 * on a border) instead of restating their coordinates.
 */
const ARCH = {
  width: 420,
  height: 300,
  boxX: 20,
  boxW: 380,
  /** arnika: the HKDF, and where both of its inputs come from. */
  arnika: { y: 14, h: 64 },
  /** The WireGuard lane: wg0, with wg1 drawn inside it because it runs inside it. */
  wg: { y: 94, h: 114 },
  /** wg1's inset from wg0's border, on each side. */
  wg1Inset: 16,
  wg1: { y: 142, h: 56 },
  /** The IPsec lane: its own arnika pair, no Rosenpass. */
  ipsec: { y: 226, h: 60 },
  /** How far right of the boxes the arnika-to-IPsec connector runs. */
  sideRail: 12,
  /** Baseline of a box's 14px title, below the box's top edge. */
  titleBaseline: 22,
  /** The same for the 13px title of the inset wg1 box, one size smaller. */
  insetTitleBaseline: 19,
  /** First 11px line below a title's baseline, then each further one. */
  firstLineGap: 16,
  lineStep: 14,
} as const;

/**
 * Baseline of line `k` in a box whose top is `top`: line 0 is the title,
 * lines 1.. are the 11px lines under it.
 */
function lineY(top: number, k: number, titleBaseline: number = ARCH.titleBaseline): number {
  return k === 0
    ? top + titleBaseline
    : top + titleBaseline + ARCH.firstLineGap + (k - 1) * ARCH.lineStep;
}

function ArchPanel() {
  const cx = ARCH.boxX + ARCH.boxW / 2;
  const right = ARCH.boxX + ARCH.boxW;
  const rail = right + ARCH.sideRail;
  const arnikaMid = ARCH.arnika.y + ARCH.arnika.h / 2;
  const ipsecMid = ARCH.ipsec.y + ARCH.ipsec.h / 2;
  const wg1X = ARCH.boxX + ARCH.wg1Inset;
  const wg1W = ARCH.boxW - 2 * ARCH.wg1Inset;
  return (
    <div style={{ background: "#0d1320", padding: 16, borderRadius: 8, border: "1px solid #1d2741" }}>
      {/* "This PoC's", not "from" the paper. In arXiv:2604.05599 arnika injects
          QKD keys into the hop WireGuard tunnels, Rosenpass runs through them,
          and its key is injected into the final WireGuard data tunnel. The
          WireGuard lane below follows that layering with wg0 and wg1. What
          this project adds: arnika's hop key also carries a PQC-HPKE key
          through HKDF-SHA3-256, and the IPsec lane. */}
      <h3 style={{ marginTop: 0 }}>This PoC&apos;s layering (extends arXiv:2604.05599)</h3>
      <svg id="overview-arch-svg" viewBox={`0 0 ${ARCH.width} ${ARCH.height}`} style={{ width: "100%" }}>
        {/* SVG text does not wrap, so every line here was measured with
            getComputedTextLength against the innermost box that contains it
            (checklist 4.2.5), in the browser on 2026-09-26. The earlier
            single-box label for Rosenpass spilled 20px past both borders of a
            380px box. In this version the widest line is the arnika
            sub-line at 307px, and the tightest clearance is 36px, the wg1
            heading against wg1's inset border (Linux fallback sans-serif). A
            first draft of the arnika sub-line ran to 370px with 5px to spare
            and was shortened. */}
        {/* arnika */}
        <rect x={ARCH.boxX} y={ARCH.arnika.y} width={ARCH.boxW} height={ARCH.arnika.h} rx="6" fill="#3a2a18" stroke="#ff9442" />
        <text x={cx} y={lineY(ARCH.arnika.y, 0)} fill="#ffd9b8" textAnchor="middle" fontSize="14">arnika: HKDF-SHA3-256 (QKD ‖ PQC-HPKE)</text>
        <text x={cx} y={lineY(ARCH.arnika.y, 1)} fill="#c8a47e" textAnchor="middle" fontSize="11">QKD key over ETSI 014 · PQC-HPKE key agreed with the peer</text>
        <text x={cx} y={lineY(ARCH.arnika.y, 2)} fill="#c8a47e" textAnchor="middle" fontSize="11">one arnika pair per lane; the two lanes share no key</text>
        {/* WireGuard lane: wg0 */}
        <rect x={ARCH.boxX} y={ARCH.wg.y} width={ARCH.boxW} height={ARCH.wg.h} rx="6" fill="#1f3322" stroke="#3ddc84" />
        <text x={cx} y={lineY(ARCH.wg.y, 0)} fill="#c4f5d8" textAnchor="middle" fontSize="14">WireGuard wg0 hop tunnel: PSK = arnika</text>
        <text x={cx} y={lineY(ARCH.wg.y, 1)} fill="#84c89c" textAnchor="middle" fontSize="11">ChaCha20-Poly1305 + Noise_IKpsk2 + preshared key</text>
        {/* wg1, inside wg0 */}
        <rect x={wg1X} y={ARCH.wg1.y} width={wg1W} height={ARCH.wg1.h} rx="5" fill="#332247" stroke="#7c5cff" />
        <text x={cx} y={lineY(ARCH.wg1.y, 0, ARCH.insetTitleBaseline)} fill="#d8c8ff" textAnchor="middle" fontSize="13">wg1 data tunnel, inside wg0: PSK = Rosenpass</text>
        <text x={cx} y={lineY(ARCH.wg1.y, 1, ARCH.insetTitleBaseline)} fill="#9d8fc8" textAnchor="middle" fontSize="11">Classic McEliece 460896 + Kyber512</text>
        <text x={cx} y={lineY(ARCH.wg1.y, 2, ARCH.insetTitleBaseline)} fill="#9d8fc8" textAnchor="middle" fontSize="11">the Rosenpass exchange itself also runs over wg0</text>
        {/* IPsec lane. */}
        <rect x={ARCH.boxX} y={ARCH.ipsec.y} width={ARCH.boxW} height={ARCH.ipsec.h} rx="6" fill="#1a2440" stroke="#5b8def" />
        <text x={cx} y={lineY(ARCH.ipsec.y, 0)} fill="#d8e1ff" textAnchor="middle" fontSize="14">IPsec/IKEv2: RFC 8784 PPK = arnika</text>
        <text x={cx} y={lineY(ARCH.ipsec.y, 1)} fill="#9aa9d8" textAnchor="middle" fontSize="11">AES-GCM-256 + ML-KEM-768 (RFC 9370) + PPK, over VICI</text>
        <text x={cx} y={lineY(ARCH.ipsec.y, 2)} fill="#9aa9d8" textAnchor="middle" fontSize="11">no Rosenpass on this lane</text>
        {/* arrows: arnika into wg0 (straight down), and arnika into the
            IPsec lane along a rail right of the boxes, ending on its border. */}
        <line x1={cx} y1={ARCH.arnika.y + ARCH.arnika.h} x2={cx} y2={ARCH.wg.y} stroke="#5b8def" strokeWidth="1.5" markerEnd="url(#arr)" />
        <polyline points={`${right},${arnikaMid} ${rail},${arnikaMid} ${rail},${ipsecMid} ${right},${ipsecMid}`}
                  fill="none" stroke="#5b8def" strokeWidth="1.5" markerEnd="url(#arr)" />
        <defs>
          <marker id="arr" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto">
            <path d="M 0 0 L 10 5 L 0 10 z" fill="#5b8def" />
          </marker>
        </defs>
      </svg>
      <p style={{ fontSize: 11, color: "#6b7796", margin: "6px 0 0", lineHeight: 1.5 }}>
        The WireGuard lane follows the paper&apos;s layering: a hop tunnel, with Rosenpass
        run through it and its key injected into the data tunnel. Additions to the
        paper: the hop tunnel&apos;s key mixes a PQC-HPKE key into the QKD key through
        HKDF-SHA3-256 (the paper keys the hops from QKD alone), and the IPsec/IKEv2 lane.
        The paper&apos;s own layering is on <Link to="/paper-flow">/paper-flow</Link>.
      </p>
      <p style={{ fontSize: 11, color: "#6b7796", margin: "6px 0 0", lineHeight: 1.5 }}>
        Note: PQC-HPKE comes from arnika pull request #51, which is still open. The arnika
        pin is that pull request&apos;s head commit (<code>f4cf9ba</code>), not a merge
        commit, and will be re-pinned to the merge commit once #51 merges.
      </p>
    </div>
  );
}

const btnStyle: React.CSSProperties = {
  background: "#1a2440", color: "#d8e1ff", border: "1px solid #2a3760",
  borderRadius: 4, padding: "2px 10px", fontSize: 11, cursor: "pointer",
};
