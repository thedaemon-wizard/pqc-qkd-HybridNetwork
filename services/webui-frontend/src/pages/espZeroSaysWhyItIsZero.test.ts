/**
 * A zero the project's own CI treats as a failure signal must say why it is
 * not one here.
 *
 * `/vpn` renders ESP byte and packet counters per CHILD_SA. On the public demo
 * they read `0 B / 0 pkt` indefinitely until 2026-09-25, under a green
 * "established" status, because nothing on the host sent traffic through the
 * tunnel. Since then `alice-ipsec`'s health check pings the peer every 15 s,
 * so a zero is legitimate only between a PPK rotation (which installs a new
 * CHILD_SA at zero) and the next probe; `start_action = trap` installs the
 * CHILD_SA on demand rather than driving traffic. Checklist row 2.11 and the
 * `ipsec` CI job both `ping` first, precisely because otherwise there may be
 * nothing to count. A zero that persists across probes is still the signature
 * the ipsec CI job treats as a policy bypass.
 *
 * But the ipsec job's own comment says:
 *
 *     A tunnel that is up but installs no ESP counters is passing traffic
 *     in the clear past the policy.
 *
 * So the page was rendering, permanently and without comment, the exact
 * signature of the one failure the CI exists to catch. A reader who knows that
 * reasoning concludes the lane is leaking plaintext.
 *
 * The fix names the missing precondition. It invents no number and takes no
 * fallback -- a genuine leak still shows as zero. What changes is that the
 * reader is told what would have to be true for the zero to be alarming.
 *
 * These assertions read the source rather than mounting React, matching the
 * other page guards in this directory.
 */
import { describe, expect, it } from "vitest";

import { readFileSync } from "node:fs";
import { join } from "node:path";

const HERE = new URL(".", import.meta.url).pathname;
const SRC = readFileSync(join(HERE, "VpnProtocols.tsx"), "utf8");

describe("an all-zero ESP reading explains itself", () => {
  it("computes whether every installed direction is idle", () => {
    expect(SRC).toMatch(/const allIdle\s*=/);
    // Guarded on there being something installed: with no CHILD_SA at all the
    // page already says "No CHILD_SA installed", and claiming "idle" there
    // would assert about a tunnel that does not exist.
    expect(SRC).toMatch(/installed\.length > 0/);
  });

  it("requires bytes AND packets to be zero in both directions", () => {
    for (const f of [/in\?\.bytes \?\? 0\) === 0/, /out\?\.bytes \?\? 0\) === 0/,
                     /in\?\.packets \?\? 0\) === 0/, /out\?\.packets \?\? 0\) === 0/]) {
      expect(SRC).toMatch(f);
    }
  });

  it("renders the explanation only in that state", () => {
    expect(SRC).toMatch(/\{allIdle && \(/);
  });

  it("names the precondition rather than excusing the zero", () => {
    // The two reasons a zero is legitimate now: a rotation has just reset the
    // counters, and the health-check probe has not fired since.
    expect(SRC).toMatch(/rotation installs a new CHILD_SA whose counters start at zero/);
    expect(SRC).toMatch(/health check every \{ESP_PROBE_INTERVAL_S\} s/);
    expect(SRC).toMatch(/Zero is expected for up to \{ESP_PROBE_INTERVAL_S\} s after each rotation\s+\(until the next health-check ping\)/);
    expect(SRC).toMatch(/start_action = trap/);
    // The reproduction, so a reader can make it non-zero themselves.
    expect(SRC).toMatch(/ping -c3 10\.30\.0\.21/);
    expect(SRC).toMatch(/2\.11/);
  });

  it("still says a zero under load would be a real leak", () => {
    // Without this the note reads as "zero is fine", which is the opposite of
    // what the CI job asserts.
    expect(SRC).toMatch(/bypassing\s*\n?\s*the policy in the clear/);
  });

  it("does not fabricate a count when the counters are absent", () => {
    // A missing direction is an em dash, never 0 -- charon omits the line it
    // has nothing for, and "no outbound line" is not "zero bytes sent".
    expect(SRC).toMatch(/: "—";/);
  });
});

describe("the note reads as prose in the browser, not as run-together words", () => {
  it("keeps a space where a code span abuts the next word", () => {
    // Measured on the deployed build: the rendered text read
    // "start_action = trapinstalls the CHILD_SA". JSX drops the newline
    // between a closing element and the following text node, so the space has
    // to be explicit. Nothing in typecheck or the assertions above could see
    // this -- only reading the rendered page could.
    expect(SRC).toMatch(/<code>start_action = trap<\/code>\{" "\}/);
  });
});

describe("the zero window is stated, not estimated", () => {
  it("claims no share of readings", () => {
    // "about a third of readings at the current ~30 s cadence" was derived
    // from nothing: the rotation gaps were measured at 30-241 s, not 30 s.
    expect(SRC).not.toMatch(/a third of/);
    expect(SRC).not.toMatch(/~30 s cadence/);
  });

  it("takes the probe interval from alice-ipsec's health check in the compose file", () => {
    const compose = readFileSync(join(HERE, "..", "..", "..", "..", "docker-compose.strongswan.yml"), "utf8");
    // alice-ipsec's is the health check that pings the peer ($PEER_IP);
    // bob-ipsec's only lists algorithms.
    const probe = /healthcheck:\s*\n\s*test:[^\n]*ping[^\n]*\n\s*interval:\s*(\d+)s/.exec(compose);
    expect(probe, "alice-ipsec's pinging health check moved; update ESP_PROBE_INTERVAL_S's source").not.toBeNull();
    const constant = /const ESP_PROBE_INTERVAL_S = (\d+);/.exec(SRC);
    expect(constant).not.toBeNull();
    expect(Number(constant![1])).toBe(Number(probe![1]));
  });
});
