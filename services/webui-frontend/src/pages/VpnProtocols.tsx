import { Fragment, useState } from "react";
import { usePoll } from "../lib/usePoll";
import { narrowColumns, useNarrowLayout } from "../lib/layout";
import ExportToolbar from "../components/ExportToolbar";
import ScrollRegion, { scrollRegionAttributes, useScrollsSideways } from "../components/ScrollRegion";
import { statusColor, wgStatusBadge } from "./wgStatusBadge";

/**
 * The two lane panels side by side, from 768px up: the template this page has
 * always used there. Below that the shell has no sidebar and the lanes stack
 * in one column (narrowColumns). Two columns on a phone were the worst case
 * measured on 2026-09-26: at a 320px viewport each panel row was about 100px
 * wide, narrower than the label "PPK required, both ends" (147px) on its own,
 * so labels ran 51px past the screen and ten values wrapped one or two
 * characters per line, the IPsec proposal string among them 570px tall.
 */
const LANE_COLUMNS = "1fr 1fr";

/**
 * The space between a row's label and its value when they share a line: the
 * `gap: 12` that Row's comment explains, named now that the narrow row also
 * uses it.
 */
const ROW_GAP_PX = 12;

/**
 * The space between a label and its value when a narrow row puts the value
 * on the line below: small, so the value still reads as that label's and not
 * as a row of its own (adjacent rows are 6px apart: Row's padding is 3px above
 * and 3px below each row).
 */
const NARROW_ROW_LINE_GAP_PX = 2;

/** The heading over the column-aligned notes, and the source of their region's name. */
const MECHANISMS_HEADING = "Two independent mechanisms — why both are needed";

/**
 * The notes' region's name: the heading's words with the em dash as a comma,
 * so the name reads the same however a screen reader treats punctuation.
 */
const MECHANISMS_REGION_LABEL = MECHANISMS_HEADING.replace(" — ", ", ");

/**
 * The narrow notes' side padding, in CSS px. The region's focus ring is drawn
 * at its edge, and without it the first column of text ran flush against the
 * ring at the left.
 */
const NARROW_NOTES_PAD_X_PX = 4;

/**
 * Poll interval, paired with the backend's VPN_SAMPLE_TTL_S (5 s): at 3 s
 * against a 2 s cache every poll from every viewer missed the cache and ran
 * five `docker exec` calls (six since wg1 is sampled too). Rotations are
 * configured at 30 s (ARNIKA_INTERVAL) and were measured 30-241 s apart, so
 * 5 s loses nothing.
 */
const VPN_POLL_MS = 5000;

/** The rotation-count window row 2.14 asks for: ten minutes. */
const ROTATION_WINDOW_S = 600;
/**
 * Rotation counts are over ten minutes and the backend caches them for
 * VPN_ROTATION_TTL_S (15 s), so polling faster than this only re-reads the
 * cache while each miss reads two containers' logs.
 */
const ROTATION_POLL_MS = 30_000;

/**
 * How often alice-ipsec's health check pings the peer through the tunnel: the
 * `interval: 15s` of its `healthcheck` in docker-compose.strongswan.yml. The
 * API does not report it, so it is stated here and
 * espZeroSaysWhyItIsZero.test.ts reads the compose file to keep the two equal.
 * It bounds how long the ESP counters can legitimately read zero after a
 * rotation installs a fresh CHILD_SA.
 */
const ESP_PROBE_INTERVAL_S = 15;

/**
 * VPN Protocols page.
 *
 * Displays the two parallel quantum-secure VPN lanes:
 *   - WireGuard (kernel module, or wireguard-go where the host has none), as
 *     two interfaces: wg0, the hop tunnel arnika keys, and wg1, the data
 *     tunnel Rosenpass keys, which runs inside wg0
 *   - strongSwan IPsec/IKEv2, RFC 9370 hybrid KE + RFC 8784 PPK
 *
 * Each lane runs its own arnika pair, and each pair derives its own
 * HKDF-SHA3-256(QKD ‖ PQC-HPKE) output, so the lanes share no key. That output
 * is written through different key-writer adapters: WireGuard's wg0 via wgctrl
 * netlink, strongSwan via a native VICI client that installs it as an RFC 8784
 * PPK. This page used to say both lanes were "fed by the same" output; the
 * QKD halves were already separate then, and since release 0.2.0 the PQC
 * halves are too (each arnika pair runs its own PQC-HPKE rounds).
 *
 * Everything shown here is parsed from the running daemon -- `swanctl
 * --list-sas` / `--list-conns` on BOTH IPsec nodes, `wg show wg0` and
 * `wg show wg1` for the WireGuard one -- and no field falls back to a constant
 * when the parse comes back empty. `null` renders as an em dash. The one
 * exception is `psk_source`, which the API labels as configuration, not
 * measurement: `wg show` says whether a preshared key is set, never who set it.
 * One value is derived rather than shown as the API gives it: each WireGuard
 * Status badge follows `peers_fresh`, not the lifetime `status` field
 * (wgStatusBadge.ts), and the JSON export keeps the API's `status`.
 *
 * Three checklist rows (2.3 PPK required on both ends, 2.11 ESP counters,
 * 2.14 rotations) used to say "Measured on the public host". The measurements
 * were real but taken over SSH: the API exposed no ESP byte or packet field,
 * and a single `ppk_required` boolean sourced only from alice-ipsec. Rows 2.3
 * and 2.11 are now on this page and in `curl /api/vpn/protocols`. Row 2.14's
 * counts come from `curl /api/vpn/ppk-rotations`, shown in the rotations
 * panel below; its SA-concurrency part still needs the shell procedure, and
 * that endpoint's own `note` says so.
 *
 * That sentence used to read "nothing on this page is a constant" and was
 * false for the WireGuard panel, in both directions: the backend returned the
 * literal "ChaCha20-Poly1305 + Noise + PSK" as `proposal` and the literal "via
 * wg show" as `last_handshake`, and this file carried its own copy of the first
 * as a `??` fallback. WireGuard negotiates no suite -- its primitives are fixed
 * by the protocol and `wg show` reports none of them -- so `proposal` is now
 * permanently null here, and the handshake rows carry the observable fact
 * instead (see WgInterface for why the handshake, and not the PSK count, is
 * that fact).
 */

interface VpnStatus {
  name: string;
  status: string;
  /**
   * Established SAs (IPsec) or peers that have completed a handshake at any
   * time since the interface came up (WireGuard). `null` means the daemon was
   * not reachable -- distinct from 0, which means it answered and there are
   * none. On WireGuard this cannot fall while the interface stays up: the
   * `latest handshake:` line it counts is never cleared. `peers_fresh` is the
   * count that can.
   */
  active_sa?: number | null;
  /**
   * WireGuard: peers whose latest handshake is younger than `fresh_within_s`,
   * so that they still hold a session key WireGuard will use. `null` when a
   * handshake age could not be read, or when the backend predates the field.
   */
  peers_fresh?: number | null;
  /**
   * WireGuard: the age limit `peers_fresh` is counted against, from the API --
   * WireGuard's REJECT_AFTER_TIME (180 s), past which a session key is
   * refused. A definition, not a measurement; given so that this page does not
   * restate the constant.
   */
  fresh_within_s?: number | null;
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
   * WireGuard: peers with SOME preshared key installed.
   *
   * `wg show` prints a peer's `preshared key:` line only when a key is set,
   * but it cannot say which key. Since release 0.2.0 the node entrypoint
   * installs a random placeholder PSK on every wg0 and wg1 peer when it
   * creates it, so this reads full before arnika or Rosenpass has written
   * anything. It is NOT evidence of keying; a recent completed handshake
   * (`peers_fresh`, `last_handshake_s`) is.
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
  /** WireGuard: which interface these fields describe ("wg0" at the top). */
  interface?: string | null;
  /**
   * WireGuard: which process writes this interface's preshared key, as
   * CONFIGURED -- "arnika: HKDF-SHA3-256(QKD || PQC-HPKE)" for wg0,
   * "rosenpass" for wg1. Not a measurement: it names whose key the interface
   * is meant to carry. A completed handshake shows that a key written on both
   * ends matched, because a placeholder on one end never matches the other
   * end's. It does not show that the latest write is the key in use; see
   * WgInterface.
   */
  psk_source?: string | null;
  /**
   * WireGuard: wg1, the end-to-end data tunnel inside wg0, in the same shape.
   * The flat fields stay wg0's.
   */
  data_tunnel?: VpnStatus | null;
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
  const narrow = useNarrowLayout();

  // Why the lanes read nothing, when they do. A failed request used to be
  // swallowed and both panels stayed on "Loading..." for good.
  const [failed, setFailed] = useState<string>("");
  // When the backend sampled the lanes, and for how long it caches a sample:
  // exported with the lanes so a saved reading says how old it is.
  const [sampled, setSampled] = useState<{ observed_at: number | null; cache_ttl_s: number | null }>(
    { observed_at: null, cache_ttl_s: null });

  async function load() {
    try {
      const r = await fetch("/api/vpn/protocols");
      const j = await r.json().catch(() => null);
      if (!r.ok) throw new Error(`HTTP ${r.status}${j?.detail ? `: ${j.detail}` : ""}`);
      setWg(j.wireguard ?? null);
      setIpsec(j.ipsec ?? null);
      setSampled({ observed_at: j.observed_at ?? null, cache_ttl_s: j.cache_ttl_s ?? null });
      setFailed("");
    } catch (e) {
      setFailed(e instanceof Error ? e.message : String(e));
    }
  }
  usePoll(load, VPN_POLL_MS);

  // Row 2.14's counts. Separate request, separate poll, separate failure: a
  // log read that fails must not blank the lane panels above.
  const [rotations, setRotations] = useState<Rotations | null>(null);
  const [rotationsFailed, setRotationsFailed] = useState<string>("");
  async function loadRotations() {
    try {
      const r = await fetch(`/api/vpn/ppk-rotations?window_s=${ROTATION_WINDOW_S}`);
      const j = await r.json().catch(() => null);
      if (!r.ok) throw new Error(`HTTP ${r.status}${j?.detail ? `: ${j.detail}` : ""}`);
      setRotations(j);
      setRotationsFailed("");
    } catch (e) {
      setRotationsFailed(e instanceof Error ? e.message : String(e));
    }
  }
  usePoll(loadRotations, ROTATION_POLL_MS);

  return (
    <div>
      <h2 style={{ marginTop: 0 }}>VPN Protocols</h2>
      <p style={{ color: "#9aa9d8", maxWidth: 760 }}>
        The PoC ships <b>two Quantum-Secure VPN lanes</b>. Each runs its own
        arnika pair, and each pair derives its own{" "}
        <code>HKDF-SHA3-256(QKD ‖ PQC-HPKE)</code> output, so the lanes share
        no key:
      </p>
      <ul style={{ color: "#cbd6f5", lineHeight: 1.7, maxWidth: 760 }}>
        <li><b>Note on the word &ldquo;PSK&rdquo;.</b> WireGuard&apos;s preshared key is
            mixed into the Noise_IKpsk2 chaining key and so contributes to the
            transport keys; the IKEv2 PSK below does not, which is why that lane
            needs RFC 8784&apos;s PPK. Same word, opposite property.</li>
        <li><b>WireGuard</b> — wg0 hop tunnel keyed by arnika (HKDF-SHA3-256
            over the QKD key and a PQC-HPKE key) + wg1 data tunnel keyed by
            Rosenpass (Classic McEliece 460896 + Kyber512). arnika writes its
            32 B WireGuard PSK into <code>wg0</code> through{" "}
            <code>wgctrl</code> netlink; Rosenpass writes its key into{" "}
            <code>wg1</code> through its own WireGuard output. wg1&apos;s peer
            endpoint is the peer&apos;s wg0 address, so wg1 runs inside wg0, and
            the Rosenpass exchange itself also runs over wg0 (the node with the
            lower wg0 address initiates it; the other end answers): the
            layering of arXiv:2604.05599, whose hop keys come from QKD
            alone.</li>
        <li><b>strongSwan IPsec/IKEv2</b> — IKEv2 with ML-KEM-768 (RFC 9370) +
            RFC 8784 PPK = arnika HKDF-SHA3-256(QKD || PQC-HPKE). A native VICI
            client installs the derived key as an <b>RFC 8784 Post-quantum
            Preshared Key</b>, on an IKE_SA negotiated with an <b>RFC 9370</b>{" "}
            hybrid proposal (the shipped default is{" "}
            <code>ecp256-ke1_mlkem768</code>, set by <code>IKE_PROPOSALS</code>;
            the Proposal row below shows what the SA actually negotiated). No
            Rosenpass on this lane.</li>
        <li><b>PQC-HPKE</b> — the PQC key arnika agrees with its peer over its
            existing UDP socket, with no key on disk: HPKE Base mode (RFC 9180)
            with the KEM MLKEM1024-P384, a hybrid of ML-KEM-1024 and P-384
            (codepoint 0x0051, from draft-ietf-hpke-pq, not yet an RFC), the
            KDF HKDF-SHA384 and an export-only AEAD. Note: it comes from arnika
            pull request #51, which is still open; the arnika pin is that pull
            request&apos;s head commit (<code>f4cf9ba</code>), not a merge
            commit, and will be re-pinned to the merge commit once #51
            merges.</li>
      </ul>
      {/* Rows 2.3 and 2.11 are read from this page, and row 2.14's counts
          from the rotations panel, so it produces evidence and must be able
          to export it. Not animated: the lanes change only on the poll. */}
      <div style={{ marginBottom: 12 }}>
        <ExportToolbar
          name="vpn-protocols"
          animated={false}
          jsonProvider={() => ({
            wireguard: wg, ipsec, ...sampled, request_failed: failed || null,
            ppk_rotations: rotations, ppk_rotations_request_failed: rotationsFailed || null,
          })}
        />
      </div>

      <div style={{ display: "grid", gridTemplateColumns: narrowColumns(narrow, LANE_COLUMNS),
                     gap: 16, marginTop: 16 }}>
        <Panel title="WireGuard (kernel / wireguard-go)" color="#3ddc84">
          {wg ? (
            <>
              <WgInterface s={wg} heading="wg0 · hop tunnel" />
              {/* wg1 beside wg0, from the same sample. `undefined` means a
                  backend from before wg1 was sampled; `null` would be the
                  backend saying it has nothing. Both read as not observed,
                  never as a healthy tunnel. */}
              {wg.data_tunnel
                ? <WgInterface s={wg.data_tunnel} heading="wg1 · data tunnel, inside wg0" />
                : <div style={{ marginTop: 10, fontSize: 12, color: "#6b7796" }}>
                    wg1 · data tunnel: — not reported by this backend —
                  </div>}
            </>
          ) : failed ? <NotObserved why={failed} /> : <Loading />}
          <p style={{ marginTop: 10, fontSize: 12, color: "#9aa9d8", lineHeight: 1.5 }}>
            <b>A recent handshake is the evidence of keying; a set PSK is not.</b>{" "}
            The preshared key enters every WireGuard handshake, so one completes
            only when both ends hold the same key, and its age says how
            recently they did. The handshake record is kept while the
            interface is up, so the Ever row stays full after the two ends
            diverge onto different keys; the Fresh row falls, and the Status
            badge turns to stale, once the last session key they shared passes
            WireGuard&apos;s REJECT_AFTER_TIME, up to that long after the
            divergence. Every peer starts with a random placeholder PSK
            that only its own node knows, so the PSK row reads full before
            arnika (wg0) or Rosenpass (wg1) has written anything. A ping
            across the interface (for wg1 at the default addresses,{" "}
            <code>docker exec alice ping -c3 10.0.1.2</code>) shows only that
            the current WireGuard session carries traffic: a new PSK takes
            effect at the next handshake, and the session key from the last
            completed one stays usable until it is REJECT_AFTER_TIME old, so
            after a divergence the ping keeps answering until then.
            Neither the handshake counts nor a ping shows that the PSK written
            most recently is in use. That takes a handshake completed after
            that write on both ends: a Last handshake age smaller than the time
            since arnika&apos;s (wg0) or Rosenpass&apos;s (wg1) last write,
            which this page does not report.
          </p>
          <p style={{ marginTop: 10, fontSize: 12, color: "#9aa9d8" }}>
            wg0 PSK path: arnika (Go) → wgctrl netlink → wg0<br />
            wg1 PSK path: Rosenpass → its WireGuard output → wg1
          </p>
        </Panel>
        <Panel title="strongSwan IPsec/IKEv2 (RFC 9370 + RFC 8784)" color="#7c5cff">
          {ipsec ? (
            <>
              <Row k="Status" v={<Badge text={ipsec.status} color={statusColor(ipsec.status)} />} />
              <Row k="Active SA" v={ipsec.active_sa ?? "—"} />
              {/* No fallback constant: an unnegotiated SA must read as such. */}
              <Row k="Proposal" v={<IpsecProposal proposal={ipsec.proposal} />} />
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
          ) : failed ? <NotObserved why={failed} /> : <Loading />}
          <p style={{ marginTop: 10, fontSize: 12, color: "#9aa9d8" }}>
            Key path: arnika → VICI <code>load-shared type=ppk</code> → charon reauth
          </p>
        </Panel>
      </div>

      <RotationsPanel r={rotations} failed={rotationsFailed} />

      <div style={{ marginTop: 24, background: "#0d1320", border: "1px solid #1d2741",
                     borderRadius: 8, padding: 14 }}>
        <h3 style={{ marginTop: 0, fontSize: 14, color: "#9aa9d8" }}>
          {MECHANISMS_HEADING}
        </h3>
        <MechanismsNote narrow={narrow} />
      </div>
    </div>
  );
}

/**
 * The column-aligned notes under the lanes.
 *
 * The lines are aligned by column, so on a narrow screen this block scrolls
 * inside itself rather than wrapping, and it is never wider than the panel it
 * sits in. From 768px up that is the <pre>'s own overflowX and maxWidth,
 * exactly as before.
 *
 * In the narrow layout the scrolling box is a ScrollRegion around the <pre>
 * instead, so that it is a named region the keyboard can reach. Measured in
 * headless Chrome 152 on 2026-09-26: the block is 570px wide and scrolls in a
 * 313px box at a 375px viewport (258px at 320px). Chrome did reach the bare
 * <pre> with Tab, because it focuses a scrolling box that holds nothing
 * focusable, and the arrow keys scrolled it. But the stop had the role
 * "generic" and, as its name, the block's whole text (2,157 characters), and
 * a browser that does not focus scrolling boxes would not reach it at all. The
 * region is the same Tab stop (the sixth at 375px) with the role "region" and
 * a short name. Inside it the <pre> has no overflowX of its own: the region is
 * the one box that scrolls, so it is the one the arrow keys scroll.
 *
 * From 768px up the <pre> itself gets the same role, Tab stop and name while
 * it scrolls, as at 768px, where it is narrower than the block, and none
 * while it does not. Attributes take no space, so its box is as before.
 */
function MechanismsNote({ narrow }: { narrow: boolean }) {
  const text = `RFC 9370 — strengthens the KEY EXCHANGE
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
         Neither appears anywhere under strongSwan 6.1.0's src/, so neither
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
    NOT an RFC 9867 indicator.`;
  const [wideRef, wideScrolls] = useScrollsSideways<HTMLPreElement>();
  const textStyle = { margin: 0, fontSize: 12, lineHeight: 1.5, color: "#cbd6f5" } as const;
  if (!narrow) {
    return (
      <pre ref={wideRef} {...scrollRegionAttributes(wideScrolls, MECHANISMS_REGION_LABEL)}
           style={{ ...textStyle, overflowX: "auto", maxWidth: "100%" }}>{text}</pre>
    );
  }
  return (
    <ScrollRegion aria-label={MECHANISMS_REGION_LABEL}>
      <pre style={{ ...textStyle, padding: `0 ${NARROW_NOTES_PAD_X_PX}px` }}>{text}</pre>
    </ScrollRegion>
  );
}

/**
 * The IPsec Proposal row's value, or "not negotiated" when there is none.
 *
 * An IKE proposal such as
 * "AES_GCM_16-256/PRF_HMAC_SHA2_384/ECP_256/KE1_ML_KEM_768/PPK" is one word to
 * the line breaker: Chrome breaks it after the hyphen and otherwise wherever
 * Row's overflowWrap "anywhere" lets it. Measured in headless Chrome 152 on
 * 2026-09-26, the narrow row broke it mid-name at a 320px viewport
 * ("...ECP_256/KE1_ML_KE" / "M_768/PPK") and left a lone "K" on the last line at
 * 375px. So in the narrow layout there is a line-break opportunity (<wbr>)
 * after every "/", and a line ends between two algorithms. <wbr> adds no
 * characters, so the value reads and copies the same. From 768px up the value
 * is the plain string, exactly as before.
 */
export function IpsecProposal({ proposal }: { proposal: string | null | undefined }) {
  const narrow = useNarrowLayout();
  if (proposal == null) return <>— not negotiated —</>;
  if (!narrow) return <>{proposal}</>;
  return <>{proposal.split("/").map((part, i, parts) => (
    <Fragment key={i}>{part}{i < parts.length - 1 && <>/<wbr /></>}</Fragment>
  ))}</>;
}

/** "n of m", or an em dash when either side was not observed. */
function ofPeers(n: number | null | undefined, peers: number | null | undefined): string {
  return n == null || peers == null ? "—" : `${n} of ${peers}`;
}

/**
 * One WireGuard interface's rows. wg0 and wg1 come in the same shape, so they
 * share this renderer and cannot drift into showing different fields.
 *
 * The handshake rows lead because they are the evidence of keying. WireGuard
 * mixes the preshared key into every handshake, so a handshake completes only
 * when both ends hold the same key: arnika's on wg0, Rosenpass's on wg1. Its
 * age says how recently that held.
 *
 * The headline is the FRESH count, not the lifetime one. `wg show` keeps a
 * peer's `latest handshake:` line for as long as the peer exists, which here
 * is as long as the interface, so the lifetime count (`active_sa`, "Ever
 * handshaked") stays full after the two ends diverge onto different keys. It
 * used to be the headline, as "Peers handshaked", and read as proof of current
 * keying. The fresh count (`peers_fresh`) keeps only peers whose latest
 * handshake is younger than WireGuard's REJECT_AFTER_TIME, the age at which
 * WireGuard refuses a session key; the backend reports that limit as
 * `fresh_within_s`, and the caption under the rows prints it. Even the fresh
 * count lags a divergence by up to that limit.
 *
 * Neither count, nor a ping across the interface, shows that the preshared key
 * written most recently is in use. A new preshared key takes effect only at
 * the next handshake, and the session keypair from the last completed one
 * stays usable until it is REJECT_AFTER_TIME old, so after the two ends
 * diverge a ping keeps answering until that keypair reaches that age. A ping
 * shows that the current WireGuard session carries traffic, and no more. What
 * shows that the latest write is in use is a handshake completed after it on
 * both ends: a latest-handshake age smaller than the time since arnika's
 * (wg0) or Rosenpass's (wg1) last write, which this page does not report. The
 * panel note says the same.
 *
 * The Status badge follows the fresh count, not the API's lifetime `status`:
 * "established" only while `peers_fresh` > 0, "stale" once a peer has
 * handshaked but none within the limit. wgStatusBadge.ts has the rules; the
 * caption under the rows says so in one line.
 *
 * The PSK row is not that evidence, and its label says so. `wg show` prints a
 * peer's `preshared key:` line whenever SOME key is set, and since release
 * 0.2.0 the entrypoint installs a random placeholder PSK on every peer when it
 * creates it, so no handshake can complete before the keying daemon has
 * written the same key on both ends. The count therefore reads full before
 * arnika or Rosenpass has written anything. It used to be labelled "Peers with
 * a WireGuard PSK" and described as direct evidence that arnika wrote the key,
 * which the placeholder made untrue.
 *
 * The labels are short on purpose. Row keeps a label whole (flexShrink 0) and
 * puts a 12px gap before the value, and at a 700px viewport a panel row is
 * 167px wide. Measured in the browser on 2026-09-26: "Peers handshaked (same
 * key)" (179px) was wider than the row on its own, and "PSK written by
 * (configured)" (165px) left no room for the gap and its value, so label, gap
 * and value together ran past the row. The labels below fit beside their
 * values. The two count labels were measured later the same day in headless
 * Chrome with the page's font stack at 13px, which reproduced the 179px and
 * 165px above: "Fresh handshakes" is 109px and "Ever handshaked" 104px, so with
 * the 12px gap each leaves room for "1 of 1" (39px in the monospace value
 * font) on one line. The definitions of "Fresh" and "Ever" therefore go in a
 * caption under the rows, not in the labels.
 *
 * Those widths were taken with the 220px sidebar at a 700px viewport. Below
 * 768px the shell now has no sidebar and the two lanes stack (LANE_COLUMNS),
 * so a row is nearly as wide as the screen, and a row too narrow for its
 * label and value puts the value on the next line (Row). The narrowest
 * two-column row is now the one at 768px: 201px, measured in headless Chrome
 * on 2026-09-26. Every label fits there with room for its value; the tightest
 * is "PSK writer (configured)" (140px), which with the gap leaves its value
 * 49px, so arnika's writer name wraps over several lines at that one width.
 */
export function WgInterface({ s, heading }: { s: VpnStatus; heading: string }) {
  const badge = wgStatusBadge(s);
  return (
    <div style={{ marginBottom: 8 }}>
      <div style={{ fontSize: 11, color: "#6b7796", marginBottom: 4 }}>{heading}</div>
      <Row k="Status" v={<Badge text={badge.text} color={badge.color} title={badge.title} />} />
      <Row k="Fresh handshakes" v={<b>{ofPeers(s.peers_fresh, s.peers)}</b>} />
      <Row k="Last handshake" v={<b>{s.last_handshake ?? "—"}</b>} />
      <Row k="Ever handshaked" v={ofPeers(s.active_sa, s.peers)} />
      {/* No fallback constant, on either lane. WireGuard negotiates no
          suite, so this reads as such rather than restating the
          protocol's fixed primitives as though they were measured. */}
      <Row k="Proposal" v={s.proposal ?? "— none negotiated (WireGuard has no suite) —"} />
      <Row k="PSK set (not proof)" v={ofPeers(s.peers_with_psk, s.peers)} />
      <Row k="PSK writer (configured)" v={s.psk_source ?? "—"} />
      <div style={{ marginTop: 4, fontSize: 11, color: "#6b7796", lineHeight: 1.5 }}>
        {s.fresh_within_s != null
          ? <>Fresh: latest handshake under {s.fresh_within_s} s old
              (WireGuard&apos;s REJECT_AFTER_TIME, the age at which it refuses
              a session key).</>
          : <>Fresh: not reported by this backend.</>}{" "}
        Ever: handshaked at least once since the interface came up; this
        count does not fall while the interface stays up. Status follows
        Fresh: established while a handshake is fresh, stale once none is,
        handshaked when Fresh is unknown; the API&apos;s <code>status</code>{" "}
        field keeps the lifetime reading.
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
 * and discarded them, so VERIFICATION_CHECKLIST row 2.11 (and the SPI-pairing
 * half of the both-ends check) could only be executed over SSH. A missing direction shows as an em dash, never as 0 --
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

  // Every installed direction reporting zero. Until 2026-09-25 that was the
  // steady state here, because nothing on the host sent anything through the
  // tunnel -- and it is indistinguishable, as rendered, from the one failure
  // the ipsec CI job exists to catch. Its own comment reads:
  //
  //     A tunnel that is up but installs no ESP counters is passing traffic
  //     in the clear past the policy.
  //
  // alice-ipsec's health check now pings the peer through the tunnel every
  // ESP_PROBE_INTERVAL_S, so the counters are non-zero except in one window:
  // each rotation reauthenticates and installs a new CHILD_SA whose counters
  // start at zero, until the next probe. How often a reading lands in that
  // window depends on the rotation gaps, which were measured at 30-241 s and
  // are not predictable from ARNIKA_INTERVAL, so no share is claimed.
  // `start_action = trap` installs the CHILD_SA on demand and generates no
  // packets itself.
  //
  // Naming the precondition is the whole fix. No number is invented, no
  // fallback is taken, and a genuine leak still shows as zero -- but the
  // reader is told what would have to be true for the zero to be alarming.
  const installed = kids.filter((k) => k.in || k.out);
  const allIdle = installed.length > 0 && installed.every(
    (k) => (k.in?.bytes ?? 0) === 0 && (k.out?.bytes ?? 0) === 0
          && (k.in?.packets ?? 0) === 0 && (k.out?.packets ?? 0) === 0);

  return (
    <div style={{ marginTop: 10, paddingTop: 8, borderTop: "1px solid #1d2741" }}>
      <div style={{ fontSize: 11, color: "#6b7796", marginBottom: 4 }}>
        ESP COUNTERS (alice&rsquo;s view)
      </div>
      {kids.map((k) => (
        <div key={`${k.name}-${k.reqid}-${k.in?.spi ?? k.out?.spi}`}
             style={{ marginBottom: 6 }}>
          {/* An ESP proposal is one unbroken token (AES_GCM_16-256/...), so
              it may break anywhere rather than run past a phone's edge. */}
          <div style={{ fontSize: 11, color: "#9aa9d8", overflowWrap: "anywhere" }}>
            {k.name} · {k.state}{k.esp_proposal ? ` · ${k.esp_proposal}` : ""}
          </div>
          <Row k="in" v={dir(k.in)} />
          <Row k="out" v={dir(k.out)} />
        </div>
      ))}
      {allIdle && (
        <p style={{ fontSize: 11, color: "#9aa9d8", margin: "6px 0 0",
                    lineHeight: 1.5 }}>
          Zero is expected for up to {ESP_PROBE_INTERVAL_S} s after each rotation
          (until the next health-check ping), and it is worth saying why:{" "}
          <b>each rotation installs a new CHILD_SA whose counters start at zero</b>, and
          the only traffic on this host is one ping from <code>alice-ipsec</code>&apos;s
          health check every {ESP_PROBE_INTERVAL_S} s. <code>start_action = trap</code>{" "}
          installs the CHILD_SA on demand rather than generating packets, so
          between a rotation and the next probe there is nothing to count. To
          see counts at once, send something across it &mdash;
          <code> docker exec alice-ipsec ping -c3 10.30.0.21</code> &mdash; which
          is what checklist row 2.11 and the <code>ipsec</code> CI job do before
          asserting a non-zero count. A reading that stays at zero across
          several probes is not this case. A tunnel that showed zero
          <i> while traffic was flowing</i> would mean packets were bypassing
          the policy in the clear; that is the case this line exists to
          distinguish, not to explain away.
        </p>
      )}
    </div>
  );
}

/** One node's counts from `GET /api/vpn/ppk-rotations`; null means "could not look". */
interface RotationNode {
  count: number | null;
  distinct_ids: number | null;
  auth_failed: number | null;
  ppk_applied: number | null;
  error?: string;
}
interface Rotations {
  window_s: number;
  requested_window_s?: number;
  capped?: boolean;
  nodes: Record<string, RotationNode>;
  counts?: Record<string, string>;
  observed_at?: number;
  note?: string;
}

/**
 * PPK rotations per IPsec node over a window -- checklist row 2.14's counts.
 *
 * This page's comment and checklist row 4.6.17 said row 2.14 was read from
 * here while nothing on the page fetched the only endpoint that serves it.
 * Every count is shown as the backend reports it; `null` (the log could not be
 * read) is an em dash with the error, never a zero.
 */
function RotationsPanel({ r, failed }: { r: Rotations | null; failed: string }) {
  const n = (x: number | null | undefined) => (x == null ? "—" : String(x));
  return (
    <div style={{ marginTop: 16 }}>
      <Panel title={`PPK rotations, last ${r ? Math.round(r.window_s / 60) : ROTATION_WINDOW_S / 60} min (row 2.14)`} color="#7c5cff">
        {!r ? (failed ? <NotObserved why={failed} /> : <Loading />) : (
          <>
            {Object.entries(r.nodes).map(([name, v]) => (
              <div key={name} style={{ marginBottom: 6 }}>
                <div style={{ fontSize: 11, color: "#9aa9d8" }}>{name}</div>
                <Row k="rotations queued ('PPK rotated')" v={n(v.count)} />
                <Row k="distinct PPK ids" v={n(v.distinct_ids)} />
                <Row k="PPK applied ('using PPK for')" v={n(v.ppk_applied)} />
                <Row k="AUTHENTICATION_FAILED" v={n(v.auth_failed)} />
                {v.error && <Row k="could not read" v={v.error} />}
              </div>
            ))}
            {r.capped && (
              <p style={{ fontSize: 11, color: "#f5a623", margin: "4px 0" }}>
                Asked for {r.requested_window_s} s; the backend capped the window at {r.window_s} s.
              </p>
            )}
            {r.note && (
              <p style={{ fontSize: 11, color: "#6b7796", margin: "6px 0 0", lineHeight: 1.5 }}>
                {r.note}
              </p>
            )}
          </>
        )}
      </Panel>
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
  const narrow = useNarrowLayout();
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
    //
    // Those rules assume the label fits with room to spare, and on a phone it
    // did not. A whole label leaves the value only what is left of the row,
    // and a value with overflowWrap "anywhere" will take one character's
    // width if that is all there is: at a 375px viewport with the lanes still
    // side by side, measured on 2026-09-26, "1 of 1", "RFC 9370 ML-KEM" and
    // "yes — mixed into SK_d" each wrapped one or two characters per line,
    // and at 320px labels kept whole ran past the screen's edge. Stacking the
    // lanes (LANE_COLUMNS) gives a row the page's width, 255px at 320px, but
    // "PSK writer (configured)" (140px) and the gap would still leave arnika's
    // writer name 103px. So in the narrow layout (below 768px) the row may
    // wrap: when label, gap and value do not fit on one line the value moves
    // to the line below, where it has the row's full width, and marginLeft
    // auto keeps it on the right. The label may shrink too, which with its
    // default minimum width means wrapping between words, only if it is wider
    // than the whole row on its own. From 768px up the row is exactly as
    // above.
    <div style={{ display: "flex", justifyContent: "space-between",
                   gap: narrow ? `${NARROW_ROW_LINE_GAP_PX}px ${ROW_GAP_PX}px` : ROW_GAP_PX,
                   padding: "3px 0", fontSize: 13,
                   ...(narrow ? { flexWrap: "wrap" } : {}) }}>
      <span style={{ color: "#9aa9d8", flexShrink: narrow ? 1 : 0 }}>{k}</span>
      <span style={{ fontFamily: "monospace", minWidth: 0, textAlign: "right",
                     overflowWrap: "anywhere",
                     ...(narrow ? { marginLeft: "auto" } : {}) }}>{v}</span>
    </div>
  );
}

function Badge({ text, color, title }: { text: string; color: string; title?: string }) {
  return (
    <span title={title}
          style={{ display: "inline-block", padding: "2px 8px", borderRadius: 12,
                    background: color, color: "#fff", fontSize: 11 }}>{text}</span>
  );
}

function NotObserved({ why }: { why: string }) {
  // `why` is the backend's error text, which can carry a path or a URL with no
  // space in it; overflowWrap lets it break instead of widening the panel.
  return <div role="status" style={{ color: "#f5a623", fontSize: 12, overflowWrap: "anywhere" }}>Not observed -- GET /api/vpn/protocols failed: {why}</div>;
}

function Loading() {
  return <div style={{ color: "#6b7796", fontSize: 12 }}>Loading…</div>;
}
