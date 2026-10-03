/**
 * The status badges on /vpn: their colours, and what the WireGuard badge says.
 *
 * The API's `status` for a WireGuard interface is a LIFETIME value. It reads
 * "established" once any peer has completed a handshake since the interface
 * came up, and it keeps reading so after the two ends diverge onto different
 * preshared keys, because `wg show` never clears a peer's `latest handshake:`
 * line (main.py, _parse_wg). The API keeps that meaning. The page did too, so
 * after a divergence it showed a green "established" badge beside "Fresh
 * handshakes 0 of 1", with only the caption under the rows to explain it.
 *
 * So the page renders the WireGuard badge from `peers_fresh`, the count that
 * can fall:
 *
 *   - "established", green, only when at least one peer's latest handshake is
 *     younger than `fresh_within_s` (WireGuard's REJECT_AFTER_TIME), so that
 *     it still holds a session key WireGuard will use;
 *   - "stale", amber, when a peer has handshaked (`active_sa > 0`) but none
 *     within that limit: no session key WireGuard will use is left;
 *   - "handshaked", neutral, when the API says established but gives no fresh
 *     count -- a handshake age it could not read, or a backend from before the
 *     field. That word is all the lifetime status establishes, and neither
 *     green nor amber would be known to be right.
 *
 * Every other status ("running", "error", "absent", ...) is shown as the API
 * gives it. The limit is always taken from the API, never restated here.
 *
 * A fresh badge does not show that the preshared key written most recently is
 * in use: a new key takes effect at the next handshake. See WgInterface in
 * VpnProtocols.tsx.
 *
 * The JSON export carries the API's `status` unchanged, so a saved reading can
 * say "established" where the page said "stale". The badge's title and the
 * caption under the rows say why.
 */

/** The page's badge colours. Amber is its existing warning colour. */
export const BADGE_OK = "#3ddc84";
export const BADGE_WARN = "#f5a623";
export const BADGE_FAULT = "#e25555";
export const BADGE_NEUTRAL = "#445";

export function statusColor(s: string): string {
  // Only "established" is green. "running" means the daemon answered but no SA
  // is up, which on this page is a lane carrying no traffic -- it shared green
  // with "established" while the WireGuard branch also degraded a FAILED
  // `wg show` to "running", so a dead lane rendered as a healthy one. The
  // backend now returns "error" for that, and "running" moves to amber because
  // it is genuinely an in-between state rather than a success.
  if (s === "established") return BADGE_OK;
  if (s === "running" || s === "restarting" || s === "rekeying") return BADGE_WARN;
  // "error" means swanctl itself failed -- charon is not answering. That must
  // read as a fault, not fall through to the neutral colour that also means
  // "absent", or a dead daemon looks unremarkable.
  if (s === "stopped" || s === "down" || s === "error") return BADGE_FAULT;
  return BADGE_NEUTRAL;
}

/** The fields of one WireGuard interface that the badge reads. */
export interface WgBadgeInput {
  status: string;
  active_sa?: number | null;
  peers_fresh?: number | null;
  fresh_within_s?: number | null;
}

export interface BadgeView {
  text: string;
  color: string;
  /** One sentence, shown as the badge's tooltip. */
  title?: string;
}

/** The API's own value of the limit when it gives one; the constant's name otherwise. */
function limit(s: WgBadgeInput): string {
  return s.fresh_within_s != null
    ? `${s.fresh_within_s} s (WireGuard's REJECT_AFTER_TIME)`
    : "WireGuard's REJECT_AFTER_TIME";
}

export function wgStatusBadge(s: WgBadgeInput): BadgeView {
  if (s.status !== "established") {
    return { text: s.status, color: statusColor(s.status) };
  }
  if (s.peers_fresh != null && s.peers_fresh > 0) {
    return {
      text: "established",
      color: BADGE_OK,
      title: `A peer's latest handshake is under ${limit(s)} old, so it still `
        + "holds a session key WireGuard will use; this does not show that the "
        + "preshared key written most recently is in use.",
    };
  }
  if (s.peers_fresh === 0 && (s.active_sa ?? 0) > 0) {
    return {
      text: "stale",
      color: BADGE_WARN,
      title: `Every peer's latest handshake is at least ${limit(s)} old, so no `
        + "session key WireGuard will use is left; the API's status still reads "
        + "established because a handshake completed since the interface came up.",
    };
  }
  return {
    text: "handshaked",
    color: BADGE_NEUTRAL,
    title: "A peer has handshaked since the interface came up, but the API gave "
      + "no fresh count (an unreadable handshake age, or a backend from before "
      + "the field), so whether a session key WireGuard will use is still held "
      + "is not known.",
  };
}
