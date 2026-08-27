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
 * Everything shown here is parsed from the running daemon -- `swanctl
 * --list-sas` / `--list-conns` on BOTH IPsec nodes, `wg show wg0` for the
 * WireGuard one -- and no field falls back to a constant when the parse comes
 * back empty. `null` renders as an em dash.
 *
 * Three checklist rows (2.3 ESP counters, 2.11 PPK on both ends, 2.14
 * rotations) used to say "Measured on the public host". The measurements were
 * real but taken over SSH: the API exposed no ESP byte or packet field, and a
 * single `ppk_required` boolean sourced only from alice-ipsec. A reader with a
 * browser could reproduce none of them. Everything those rows assert is now on
 * this page and in `curl /api/vpn/protocols`.
 *
 * That sentence used to read "nothing on this page is a constant" and was
 * false for the WireGuard panel, in both directions: the backend returned the
 * literal "ChaCha20-Poly1305 + Noise + PSK" as `proposal` and the literal "via
 * wg show" as `last_handshake`, and this file carried its own copy of the first
 * as a `??` fallback. WireGuard negotiates no suite -- its primitives are fixed
 * by the protocol and `wg show` reports none of them -- so `proposal` is now
 * permanently null here, and `peers_with_psk` carries the observable fact
 * instead.
 */

interface VpnStatus {
  name: string;
  status: string;
  /**
   * Established SAs (IPsec) or peers that have completed a handshake
   * (WireGuard). `null` means the daemon was not reachable -- distinct from 0,
   * which means it answered and there are none.
   */
  active_sa?: number | null;
  /**
   * Negotiated IKE_SA proposal, or null before the SA is up.
   *
   * Always null on the WireGuard lane. See the note above: there is nothing in
   * `wg show` to derive one from, so a value here could only be invented.
   */
  proposal?: string | null;
  last_handshake?: string | null;
  /** Handshake age in seconds. 0 is a measurement; null is the lack of one. */
  last_handshake_s?: number | null;
  /** WireGuard: peers configured on the interface. */
  peers?: number | null;
  /**
   * WireGuard: peers with a preshared key installed.
   *
   * `wg show` prints a peer's `preshared key:` line only when one is actually
   * set, so this is direct evidence that arnika wrote the QKD-derived key.
   * Worth showing because the failure is silent: a peer without the PSK still
   * brings the tunnel up and passes traffic on Noise alone.
   */
  peers_with_psk?: number | null;
  /**
   * RFC 9370: an additional ML-KEM key exchange was negotiated.
   *
   * Genuinely tri-state now. `false` means the proposal was read and carries
   * no ML-KEM -- a finding. `null` means no proposal was available.
   */
  pq_key_exchange?: boolean | null;
  /**
   * RFC 8784: whether the PPK was actually USED for this IKE_SA.
   *
   * Read from the `/PPK` suffix strongSwan appends to the proposal line, which
   * it sets from COND_PPK -- a flag raised in `apply_ppk()` only after the PPK
   * has been mixed into SK_d/SK_pi/SK_pr. Proof of use, not of configuration.
   * `ppk_required` below is the configuration, and the two fail independently:
   * a required PPK that never arrives is the case worth seeing.
   */
  ppk_used?: boolean | null;
  /** RFC 8784: PPK identity configured on the connection. */
  ppk_id?: string | null;
  ppk_required?: boolean | null;
  /** Per-CHILD_SA ESP counters and SPIs, parsed from `swanctl --list-sas`. */
  child_sas?: ChildSa[] | null;
  /** Per-node views. The flat fields above remain alice's. */
  nodes?: Record<string, VpnStatus>;
  ppk_required_both_ends?: boolean | null;
  ppk_used_both_ends?: boolean | null;
  pq_key_exchange_both_ends?: boolean | null;
  /**
   * alice's outbound SPI is bob's inbound one, and vice versa.
   *
   * The only aggregate here that one end could not fabricate: an SPI is chosen
   * by the receiver and echoed by the sender, so a match proves both nodes
   * describe the SAME pair of ESP SAs rather than two unrelated tunnels that
   * both happen to be up.
   */
  spi_paired?: boolean | null;
}

interface ChildSa {
  name: string;
  state: string;
  reqid: number;
  esp_proposal?: string | null;
  /** null when charon printed no line for that direction -- not zero. */
  in?: { spi: string; bytes: number; packets: number } | null;
  out?: { spi: string; bytes: number; packets: number } | null;
}

/** Tri-state renderer: yes / no / unknown must be three distinct readings. */
function TriState({ v, yes, no }: { v: boolean | null | undefined; yes: string; no: string }) {
  if (v === true) return <span style={{ color: "#3ddc84" }}>{yes}</span>;
  if (v === false) return <span style={{ color: "#e25555" }}>{no}</span>;
  return <span style={{ color: "#6b7796" }}>— not observed —</span>;
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
        <li><b>Note on the word &ldquo;PSK&rdquo;.</b> WireGuard&apos;s preshared key is
            mixed into the Noise_IKpsk2 chaining key and so contributes to the
            transport keys; the IKEv2 PSK below does not, which is why that lane
            needs RFC 8784&apos;s PPK. Same word, opposite property.</li>
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
              <Row k="Peers handshaked" v={wg.active_sa ?? "—"} />
              {/* No fallback constant, on either lane. WireGuard negotiates no
                  suite, so this reads as such rather than restating the
                  protocol's fixed primitives as though they were measured. */}
              <Row k="Proposal" v={wg.proposal ?? "— none negotiated (WireGuard has no suite) —"} />
              <Row k="Last handshake" v={wg.last_handshake ?? "—"} />
              {/* The one observable security fact here: `wg show` prints a
                  peer's `preshared key:` line only when one is installed. */}
              <Row k="Peers with QKD PSK" v={
                wg.peers_with_psk == null || wg.peers == null
                  ? "—"
                  : `${wg.peers_with_psk} of ${wg.peers}`
              } />
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
              <Row k="Active SA" v={ipsec.active_sa ?? "—"} />
              {/* No fallback constant: an unnegotiated SA must read as such. */}
              <Row k="Proposal" v={ipsec.proposal ?? "— not negotiated —"} />
              {/* `? :` would render "no" for "unknown" -- see TriState. */}
              <Row k="PQ key exchange" v={
                <TriState v={ipsec.pq_key_exchange} yes="RFC 9370 ML-KEM" no="classical only" />
              } />
              <Row k="PPK in use (this SA)" v={
                <TriState v={ipsec.ppk_used} yes="yes — mixed into SK_d" no="NO — fell back to NO_PPK_AUTH" />
              } />
              <Row k="PPK configured" v={
                ipsec.ppk_id
                  ? `${ipsec.ppk_id}${ipsec.ppk_required ? " (required)" : " (optional)"}`
                  : "— not configured —"
              } />
              <Row k="Last handshake" v={ipsec.last_handshake ?? "—"} />
              <BothEnds s={ipsec} />
              <EspCounters kids={ipsec.child_sas} />
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
    requires a reauthentication, not a rekey. RFC 9867 (Nov 2025) lifts this;
    it names QKD explicitly as the motivating case.
  - Two observations about RFC 9867 here, rather than a claim that it is
    unimplemented -- a build option we do not know about would make a flat
    claim wrong, and both of these are reproducible in a minute:
      1. RFC 9867 needs USE_PPK_INT (16445) and PPK_IDENTITY_KEY (16446).
         Neither appears anywhere under strongSwan 6.0.7's src/, so neither
         can be sent or parsed. Note where they would sit: notify_payload.h
         carries USE_PPK (16435), PPK_IDENTITY (16436), NO_PPK_AUTH (16437),
         INTERMEDIATE_EXCHANGE_SUPPORTED (16438), ADDITIONAL_KEY_EXCHANGE
         (16441), USE_AGGFRAG (16442) and SA_RESOURCE_INFO (16444) -- 16444
         is the highest Status Type in the enum, and the next entry is
         INITIAL_CONTACT_IKEV1 (24578). So 16445 and 16446 are the two values
         immediately above the top of the range, not a gap in the middle.
      2. The IKE_SA_INIT response on this lane carries N(USE_PPK). RFC 9867
         s3.1 has a responder return either USE_PPK_INT or USE_PPK and never
         both, so that single notify settles which specification is running.
    Note that N(IKE_INT_SUP) also appears on this lane; it is RFC 9242's
    intermediate exchange, present for RFC 9370's ML-KEM key exchange, and is
    NOT an RFC 9867 indicator.`}
        </pre>
      </div>
    </div>
  );
}

/**
 * Facts that need BOTH ends to be known.
 *
 * The aggregates are computed server-side, not here, and that is deliberate:
 * `null && true` is falsy in JavaScript, so `a.ppk_used && b.ppk_used` in this
 * file would render "not in use" whenever one end merely failed to answer --
 * turning an unknown into a negative finding. The backend keeps the three
 * outcomes distinct and this component just displays them.
 */
function BothEnds({ s }: { s: VpnStatus }) {
  const nodes = s.nodes;
  if (!nodes) return null;
  return (
    <div style={{ marginTop: 10, paddingTop: 8, borderTop: "1px solid #1d2741" }}>
      <div style={{ fontSize: 11, color: "#6b7796", marginBottom: 4 }}>
        BOTH ENDS ({Object.keys(nodes).join(" + ")})
      </div>
      <Row k="PPK required, both ends" v={
        <TriState v={s.ppk_required_both_ends} yes="yes" no="not on both" />
      } />
      <Row k="PPK in use, both ends" v={
        <TriState v={s.ppk_used_both_ends} yes="yes" no="NOT on both" />
      } />
      <Row k="ML-KEM, both ends" v={
        <TriState v={s.pq_key_exchange_both_ends} yes="yes" no="not on both" />
      } />
      <Row k="SPIs pair across ends" v={
        <TriState v={s.spi_paired} yes="yes — same ESP SAs" no="NO — different tunnels" />
      } />
    </div>
  );
}

/**
 * ESP byte and packet counters, per CHILD_SA.
 *
 * These have always been in `swanctl --list-sas`; the API fetched that output
 * and discarded them, so VERIFICATION_CHECKLIST rows 2.3 and 2.11 could only
 * be executed over SSH. A missing direction shows as an em dash, never as 0 --
 * charon omits the line it has nothing for, and "no outbound line" is not
 * "zero bytes sent".
 */
function EspCounters({ kids }: { kids?: ChildSa[] | null }) {
  if (!kids) return null;
  if (!kids.length) {
    return (
      <div style={{ marginTop: 10, fontSize: 12, color: "#6b7796" }}>
        No CHILD_SA installed.
      </div>
    );
  }
  const dir = (d?: { spi: string; bytes: number; packets: number } | null) =>
    d ? `${d.spi}  ${d.bytes.toLocaleString()} B / ${d.packets.toLocaleString()} pkt` : "—";
  return (
    <div style={{ marginTop: 10, paddingTop: 8, borderTop: "1px solid #1d2741" }}>
      <div style={{ fontSize: 11, color: "#6b7796", marginBottom: 4 }}>
        ESP COUNTERS (alice&rsquo;s view)
      </div>
      {kids.map((k) => (
        <div key={`${k.name}-${k.reqid}-${k.in?.spi ?? k.out?.spi}`}
             style={{ marginBottom: 6 }}>
          <div style={{ fontSize: 11, color: "#9aa9d8" }}>
            {k.name} · {k.state}{k.esp_proposal ? ` · ${k.esp_proposal}` : ""}
          </div>
          <Row k="in" v={dir(k.in)} />
          <Row k="out" v={dir(k.out)} />
        </div>
      ))}
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
    // `gap` and the shrink rules are load-bearing, not tidying.
    //
    // This was a bare `space-between` with two auto-width spans. Nothing
    // overflowed the panel -- the value wrapped -- but with no minimum gap the
    // label and the value ABUT, and at a 700px content width the IPsec row
    // rendered as `ProposalAES_GCM_16-256/PRF_HMAC_SHA2_384/...`, one
    // unreadable token. Measured in the browser against the deployed demo on
    // 2026-08-27: first collision at ~900px, three rows by 600px.
    //
    // Same failure mode as the Overview label that spilled its box: fine at
    // the width it was written at, wrong at a common one, and invisible to
    // every headless assertion because it is a rendering property.
    //
    // flexShrink 0 on the key keeps the label whole; minWidth 0 lets the value
    // wrap inside its own column instead of pushing into the label; textAlign
    // right keeps a wrapped value visually attached to its own side.
    <div style={{ display: "flex", justifyContent: "space-between",
                   gap: 12, padding: "3px 0", fontSize: 13 }}>
      <span style={{ color: "#9aa9d8", flexShrink: 0 }}>{k}</span>
      <span style={{ fontFamily: "monospace", minWidth: 0, textAlign: "right",
                     overflowWrap: "anywhere" }}>{v}</span>
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
  // Only "established" is green. "running" means the daemon answered but no SA
  // is up, which on this page is a lane carrying no traffic -- it shared green
  // with "established" while the WireGuard branch also degraded a FAILED
  // `wg show` to "running", so a dead lane rendered as a healthy one. The
  // backend now returns "error" for that, and "running" moves to amber because
  // it is genuinely an in-between state rather than a success.
  if (s === "established") return "#3ddc84";
  if (s === "running" || s === "restarting" || s === "rekeying") return "#f5a623";
  // "error" means swanctl itself failed -- charon is not answering. That must
  // read as a fault, not fall through to the neutral colour that also means
  // "absent", or a dead daemon looks unremarkable.
  if (s === "stopped" || s === "down" || s === "error") return "#e25555";
  return "#445";
}

function Loading() {
  return <div style={{ color: "#6b7796", fontSize: 12 }}>Loading…</div>;
}
