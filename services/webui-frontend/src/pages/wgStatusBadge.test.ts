/**
 * The /vpn WireGuard badge follows the fresh handshake count, not the API's
 * lifetime `status`.
 *
 * `status` reads "established" once any peer has handshaked since the
 * interface came up, and `wg show` never clears that record, so after the two
 * ends diverged onto different preshared keys the page showed a green
 * "established" beside "Fresh handshakes 0 of 1". The API keeps its meaning;
 * the page renders "established" only while `peers_fresh` > 0 and "stale" once
 * a peer has handshaked but none within `fresh_within_s`.
 *
 * The second half pins what the panel may say a ping shows. A new preshared
 * key takes effect only at the next handshake, and the old session keypair
 * stays usable until it is REJECT_AFTER_TIME old, so a ping keeps answering
 * after a divergence. It shows that the current session carries traffic and
 * nothing about which key was written last.
 */
import { describe, expect, it } from "vitest";

import { readFileSync } from "node:fs";
import { join } from "node:path";

import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";

import { WgInterface } from "./VpnProtocols";
import {
  BADGE_NEUTRAL, BADGE_OK, BADGE_WARN, statusColor, wgStatusBadge,
} from "./wgStatusBadge";

const HERE = new URL(".", import.meta.url).pathname;
const VPN = readFileSync(join(HERE, "VpnProtocols.tsx"), "utf8");
const BADGE_SRC = readFileSync(join(HERE, "wgStatusBadge.ts"), "utf8");
const MAIN_PY = readFileSync(join(HERE, "..", "..", "..", "webui-backend", "app", "main.py"), "utf8");
const norm = (s: string) => s.replace(/\s+/g, " ");
/** Comment text with its line markers (` * `, `//`, `#`) removed, then collapsed. */
const prose = (s: string) => norm(s.replace(/^[ \t]*(?:\*|\/\/|#)[ \t]?/gm, ""));
/** Source with its comments removed: what the page renders. */
const code = (s: string) => s.replace(/\/\*[\s\S]*?\*\//g, "").replace(/(?<!:)\/\/[^\n]*/g, "");

/** A limit that is not WireGuard's, to show the text takes the API's value. */
const API_LIMIT_S = 42;

/** What the backend returns for one peer that handshaked `fresh` or not. */
const wgIface = (over: Record<string, unknown>) => ({
  name: "wireguard", status: "established", active_sa: 1, peers_fresh: 1,
  fresh_within_s: API_LIMIT_S, peers: 1, peers_with_psk: 1,
  last_handshake: "12s ago", last_handshake_s: 12, proposal: null,
  psk_source: "rosenpass", ...over,
});

describe("the WireGuard badge reads from peers_fresh", () => {
  it("is established, in green, only while a handshake is fresh", () => {
    const b = wgStatusBadge(wgIface({}));
    expect(b.text).toBe("established");
    expect(b.color).toBe(BADGE_OK);
    expect(b.color).toBe(statusColor("established"));
  });

  it("is stale, in the warning colour, once a peer has handshaked but none is fresh", () => {
    const b = wgStatusBadge(wgIface({ peers_fresh: 0, last_handshake_s: 200 }));
    expect(b.text).toBe("stale");
    expect(b.color).toBe(BADGE_WARN);
    expect(b.color).not.toBe(BADGE_OK);
  });

  it("explains the window in one sentence, with the limit from the API", () => {
    const b = wgStatusBadge(wgIface({ peers_fresh: 0 }));
    expect(b.title).toContain(`${API_LIMIT_S} s (WireGuard's REJECT_AFTER_TIME)`);
    expect(b.title).toContain("the API's status still reads established");
    expect(b.title!.split(/(?<=\.)\s/).length, "more than one sentence").toBe(1);
  });

  it("names the constant rather than a number when the API gives no limit", () => {
    const b = wgStatusBadge(wgIface({ peers_fresh: 0, fresh_within_s: null }));
    expect(b.text).toBe("stale");
    expect(b.title).toContain("WireGuard's REJECT_AFTER_TIME");
    expect(b.title).not.toMatch(/\d+ s\b/);
  });

  it("is never green when the fresh count is unknown", () => {
    // An unreadable handshake age (null), and a backend from before the field
    // (undefined): the lifetime status alone says only that a peer handshaked.
    for (const peers_fresh of [null, undefined]) {
      const b = wgStatusBadge(wgIface({ peers_fresh }));
      expect(b.text, String(peers_fresh)).toBe("handshaked");
      expect(b.color).toBe(BADGE_NEUTRAL);
      expect(b.title).toContain("is not known");
    }
  });

  it("does not call a peer stale that never handshaked", () => {
    const b = wgStatusBadge(wgIface({ peers_fresh: 0, active_sa: 0 }));
    expect(b.text).not.toBe("stale");
    expect(b.color).not.toBe(BADGE_OK);
  });

  it("shows every other status as the API gives it", () => {
    for (const status of ["running", "error", "absent", "down"]) {
      const b = wgStatusBadge(wgIface({ status, peers_fresh: null, active_sa: 0 }));
      expect(b.text).toBe(status);
      expect(b.color).toBe(statusColor(status));
    }
  });

  it("gives each state its own word", () => {
    const words = [
      wgStatusBadge(wgIface({})).text,
      wgStatusBadge(wgIface({ peers_fresh: 0 })).text,
      wgStatusBadge(wgIface({ peers_fresh: null })).text,
      wgStatusBadge(wgIface({ status: "running", active_sa: 0, peers_fresh: 0 })).text,
    ];
    expect(new Set(words).size).toBe(words.length);
  });

  it("does not restate REJECT_AFTER_TIME's value", () => {
    const code = BADGE_SRC.replace(/\/\*[\s\S]*?\*\//g, "").replace(/\/\/[^\n]*/g, "");
    expect(code).not.toMatch(/\b180\b/);
  });
});

describe("/vpn renders that badge", () => {
  const render = (over: Record<string, unknown>) =>
    renderToStaticMarkup(createElement(WgInterface, { s: wgIface(over), heading: "wg1" }));

  it("a stale interface reads stale on the page, with the tooltip", () => {
    const html = render({ peers_fresh: 0, last_handshake: "200s ago", last_handshake_s: 200 });
    expect(html).toMatch(/title="Every peer&#x27;s latest handshake is at least 42 s[^"]*"[^>]*>stale</);
    expect(html).not.toMatch(/>established</);
  });

  it("a fresh interface reads established", () => {
    expect(render({})).toMatch(/>established</);
  });

  it("the caption says the badge follows Fresh and the API field does not", () => {
    const text = norm(render({}).replace(/<[^>]+>/g, "")).replace(/&#x27;/g, "'");
    expect(text).toContain("Status follows Fresh: established while a handshake is fresh, stale once none is");
    expect(text).toContain("the API's status field keeps the lifetime reading");
  });

  it("the IPsec badge still shows the API's status", () => {
    expect(VPN).toContain("<Badge text={ipsec.status} color={statusColor(ipsec.status)} />");
  });
});

describe("a ping is not said to show the latest key", () => {
  const vpn = prose(VPN);
  const py = prose(MAIN_PY);
  // Any sentence in which a ping shows or proves the current, latest,
  // installed or "now" key.
  const CLAIM = new RegExp(
    String.raw`\bping\b[^.]{0,80}\b(?:shows?|proves?|proof)\b[^.]{0,40}`
    + String.raw`(?:\b(?:current|latest|installed|now)\b[^.]{0,20}\b(?:key|PSK)\b`
    + String.raw`|\b(?:key|PSK)\b[^.]{0,20}\b(?:installed|now|latest|matches)\b)`, "i");
  const sentences = (t: string) => t.split(/(?<=\.)\s+/);

  it("the guard catches the claims it exists for", () => {
    for (const bad of [
      "A ping shows that the current key is in use.",
      "A ping across the interface proves the installed PSK.",
      "The ping shows that the key installed now matches.",
      "Proof: a ping over wg1 shows the latest PSK carries traffic.",
    ]) {
      expect(sentences(bad).some((x) => CLAIM.test(x)), bad).toBe(true);
    }
  });

  it("the retired claims are gone, from comments too", () => {
    expect(vpn).not.toContain("That is what the ping in the panel note is for");
    expect(vpn).not.toContain("Showing that the current key carries traffic takes a ping");
    expect(py).not.toContain("Proof that the current key carries traffic is a ping");
    for (const [name, t] of [["VpnProtocols.tsx", vpn], ["main.py", py]] as const) {
      for (const sentence of sentences(t)) {
        expect(sentence, `${name}: ${sentence}`).not.toMatch(CLAIM);
      }
    }
  });

  it("the panel says what a ping shows and what shows the latest write", () => {
    const panel = norm(code(VPN)).replace(/&apos;/g, "'");
    expect(panel).toContain("shows only that the current WireGuard session carries traffic");
    expect(panel).toContain("stays usable until it is REJECT_AFTER_TIME old");
    expect(panel).toContain(
      "Neither the handshake counts nor a ping shows that the PSK written most recently is in use.");
    expect(panel).toContain(
      "a Last handshake age smaller than the time since arnika's (wg0) or Rosenpass's (wg1) last write");
  });

  it("the WgInterface comment and the backend comment say the same", () => {
    expect(vpn).toContain("A ping shows that the current WireGuard session carries traffic, and no more.");
    expect(py).toContain("shows only that the current WireGuard session carries traffic");
    expect(py).toContain(
      "a `last_handshake_s` smaller than the time since arnika's (wg0) or Rosenpass's (wg1) last write");
  });
});
