/**
 * A zero the project's own CI treats as a failure signal must say why it is
 * not one here.
 *
 * `/vpn` renders ESP byte and packet counters per CHILD_SA. On the public demo
 * they read `0 B / 0 pkt` indefinitely, under a green "established" status.
 *
 * That zero is CORRECT: nothing on that host sends anything through the
 * tunnel. There is no ping, no keepalive and no health check that traverses
 * it, and `start_action = trap` installs the CHILD_SA on demand rather than
 * driving traffic. Checklist row 2.11 and the `ipsec` CI job both `ping`
 * first, precisely because otherwise there is nothing to count.
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
    expect(SRC).toMatch(/nothing on this\s*\n?\s*host sends traffic through the tunnel/);
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
