/**
 * The live lanes are described the way release 0.2.0 deploys them.
 *
 * Until 0.2.0 a Rosenpass sidecar on each node wrote a PQC key to a file,
 * arnika read that file as the PQC half of its HKDF, and both lanes consumed
 * the result. The arnika pin moved to the head of upstream PR #51, which
 * removed that file interface: arnika now agrees the PQC half with its peer by
 * PQC-HPKE, and Rosenpass keys a second WireGuard interface, wg1, that runs
 * inside the wg0 hop tunnel. Every page that described the old wiring would
 * have gone on describing it, because nothing it renders is derived from the
 * pin. So the wording is pinned here instead:
 *
 *   * one sentence per lane, identical on /  and /vpn, so the two pages cannot
 *     drift into describing different stacks;
 *   * PQC-HPKE is defined wherever it is named, including that its KEM comes
 *     from an Internet-Draft and not an RFC;
 *   * no live page says Rosenpass feeds arnika or writes a key file;
 *   * the pin is said to be an unmerged PR head, and no page claims that the
 *     PR's rotation-ordering commit fixes the intermittent PPK mismatch -- that
 *     has not been measured.
 *
 * These read the source rather than mounting React, matching the other page
 * guards in this directory. Whitespace is collapsed first, because JSX text
 * wraps across source lines and renders with single spaces.
 */
import { describe, expect, it } from "vitest";

import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";

const HERE = new URL(".", import.meta.url).pathname;
const SRC_DIR = join(HERE, "..");
const read = (rel: string) => readFileSync(join(SRC_DIR, rel), "utf8");
const norm = (s: string) => s.replace(/\s+/g, " ");

const APP = read("App.tsx");
const OVERVIEW = read("pages/Overview.tsx");
const VPN = read("pages/VpnProtocols.tsx");
const KEYFLOW = read("pages/KeyFlow.tsx");

/** The two lane sentences, word for word as the docs state them. */
const WIREGUARD_LANE =
  "wg0 hop tunnel keyed by arnika (HKDF-SHA3-256 over the QKD key and a PQC-HPKE key) "
  + "+ wg1 data tunnel keyed by Rosenpass (Classic McEliece 460896 + Kyber512)";
const IPSEC_LANE =
  "IKEv2 with ML-KEM-768 (RFC 9370) + RFC 8784 PPK = arnika HKDF-SHA3-256(QKD || PQC-HPKE)";

/** Pages that describe the running stack, as opposed to the paper or a simulation. */
const LIVE_PAGES = [
  "App.tsx", "pages/Overview.tsx", "pages/VpnProtocols.tsx", "pages/KeyFlow.tsx",
  "pages/keyFlowGraph.ts", "pages/Topology.tsx", "pages/PQCValidator.tsx",
  "pages/Console.tsx", "lib/sim/pqc.ts",
];

/** Strip comments: they record history, including the retired wiring, on purpose. */
const code = (s: string) => s.replace(/\/\*[\s\S]*?\*\//g, "").replace(/(?<!:)\/\/[^\n]*/g, "");

describe("each lane has one description, and / and /vpn both give it", () => {
  for (const [name, text] of [["Overview.tsx", OVERVIEW], ["VpnProtocols.tsx", VPN]] as const) {
    it(`${name} states the WireGuard lane`, () => {
      expect(norm(text)).toContain(WIREGUARD_LANE);
    });
    it(`${name} states the IPsec lane`, () => {
      expect(norm(text)).toContain(IPSEC_LANE);
    });
    it(`${name} says the IPsec lane has no Rosenpass`, () => {
      expect(norm(code(text))).toMatch(/no Rosenpass/i);
    });
  }
});

describe("PQC-HPKE is defined where it is named", () => {
  for (const [name, text] of [
    ["Overview.tsx", OVERVIEW], ["VpnProtocols.tsx", VPN], ["KeyFlow.tsx", KEYFLOW],
  ] as const) {
    it(`${name} gives the mode, the KEM and its status`, () => {
      const t = norm(code(text));
      expect(t).toContain("HPKE Base mode (RFC 9180)");
      expect(t).toContain("MLKEM1024-P384");
      // A hybrid, and from a draft: the two facts most easily lost.
      expect(t).toContain("a hybrid of ML-KEM-1024 and P-384");
      expect(t).toContain("draft-ietf-hpke-pq, not yet an RFC");
      expect(t).toContain("HKDF-SHA384");
      expect(t).toContain("export-only AEAD");
    });
  }

  it("the codepoint is given where the suite is introduced", () => {
    for (const text of [OVERVIEW, VPN]) {
      expect(norm(code(text))).toContain("codepoint 0x0051");
    }
  });
});

describe("no live page says Rosenpass feeds arnika", () => {
  for (const rel of LIVE_PAGES) {
    it(`${rel} has none of the retired wiring`, () => {
      const t = norm(code(read(rel)));
      expect(t, "the key file Rosenpass used to write for arnika").not.toMatch(/pqc\.psk/);
      expect(t).not.toMatch(/Rosenpass sidecar/i);
      expect(t).not.toMatch(/mixes a Rosenpass key/);
      // The HKDF's PQC input is named as PQC-HPKE, never as a bare "PQC".
      expect(t, "an HKDF input written as bare PQC").not.toMatch(/QKD ?(‖|\|\|) ?PQC(?!-HPKE)/);
    });
  }
});

describe("the sidebar names each algorithm's owner", () => {
  const sidebar = /<div style=\{\{ marginTop: 36[^>]*>([\s\S]*?)<\/div>/.exec(APP)?.[1] ?? "";
  const lines = sidebar.split("<br />").map((l) => l.trim());

  it("is found", () => {
    expect(lines.length, "the sidebar block moved; this test is now vacuous").toBeGreaterThan(3);
  });

  it("lists the HKDF, PQC-HPKE, IKEv2 and wg1 lines", () => {
    expect(lines).toContain("HKDF-SHA3-256: QKD, PQC-HPKE");
    expect(lines).toContain("PQC-HPKE: ML-KEM-1024 + P-384");
    expect(lines).toContain("IKEv2: ML-KEM-768 (RFC 9370)");
    expect(lines).toContain("wg1 PSK: Rosenpass");
    expect(lines).toContain("Rosenpass: McEliece + Kyber512");
  });

  it("keeps the IKEv2 line between the PQC-HPKE line and the Rosenpass line", () => {
    // tests/test_rosenpass_kem_names_match_the_submodule.py flags Rosenpass
    // within 70 characters of an unattributed ML-KEM name, across line breaks.
    const at = (s: string) => lines.findIndex((l) => l.startsWith(s));
    expect(at("PQC-HPKE:")).toBeGreaterThan(-1);
    expect(at("PQC-HPKE:")).toBeLessThan(at("IKEv2:"));
    expect(at("IKEv2:")).toBeLessThan(at("wg1 PSK:"));
    expect(at("IKEv2:")).toBeLessThan(at("Rosenpass:"));
  });
});

describe("/vpn shows wg1 beside wg0", () => {
  it("renders the data tunnel from the same sample with the same rows", () => {
    expect(VPN).toMatch(/<WgInterface s=\{wg\} heading="wg0 · hop tunnel" \/>/);
    expect(VPN).toMatch(/<WgInterface s=\{wg\.data_tunnel\} heading="wg1 · data tunnel, inside wg0" \/>/);
  });

  it("says when the backend reports no wg1, rather than showing nothing", () => {
    expect(VPN).toMatch(/wg1 · data tunnel: — not reported by this backend —/);
  });

  it("shows who writes each PSK as configuration, from the API", () => {
    expect(VPN).toMatch(/<Row k="PSK writer \(configured\)" v=\{s\.psk_source \?\? "—"\} \/>/);
  });

  // Since release 0.2.0 the entrypoint installs a random placeholder PSK on
  // every wg0 and wg1 peer at creation, so a `preshared key:` line no longer
  // shows that arnika or Rosenpass wrote anything. A RECENT completed
  // handshake does. `wg show` keeps a peer's `latest handshake:` line while
  // the interface is up, so a count of peers that ever handshaked stays full
  // after the two ends diverge; the fresh count (younger than WireGuard's
  // REJECT_AFTER_TIME) is the one that can fall, and it is the headline.
  const wgRows = /function WgInterface[\s\S]*?\n}\n/.exec(VPN)?.[0] ?? "";
  const rowAt = (label: string) => wgRows.indexOf(`<Row k="${label}"`);

  it("leads with the fresh handshake count and labels the PSK count as not proof", () => {
    expect(wgRows, "WgInterface moved; this test is now vacuous").not.toBe("");
    for (const label of ["Fresh handshakes", "Last handshake", "Ever handshaked",
                         "PSK set (not proof)"]) {
      expect(rowAt(label), label).toBeGreaterThan(-1);
    }
    // Status first, then the recency rows, before anything else.
    expect(rowAt("Status")).toBeLessThan(rowAt("Fresh handshakes"));
    expect(rowAt("Fresh handshakes")).toBeLessThan(rowAt("Last handshake"));
    expect(rowAt("Last handshake")).toBeLessThan(rowAt("Ever handshaked"));
    expect(rowAt("Ever handshaked")).toBeLessThan(rowAt("Proposal"));
    expect(rowAt("Ever handshaked")).toBeLessThan(rowAt("PSK set (not proof)"));
    // The retired labels: one read a full PSK count as "keyed", the other a
    // lifetime handshake count as current keying.
    expect(norm(code(VPN))).not.toContain("Peers with a WireGuard PSK");
    expect(rowAt("Peers handshaked"), "the lifetime count is back as the headline").toBe(-1);
  });

  it("reads each count from its own field, and bolds only the fresh one", () => {
    expect(wgRows).toContain('<Row k="Fresh handshakes" v={<b>{ofPeers(s.peers_fresh, s.peers)}</b>} />');
    expect(wgRows).toContain('<Row k="Ever handshaked" v={ofPeers(s.active_sa, s.peers)} />');
  });

  it("defines both counts under the rows, with the limit taken from the API", () => {
    const t = norm(code(wgRows));
    expect(t).toContain("since the interface came up");
    expect(t).toContain("REJECT_AFTER_TIME");
    expect(t).toContain("{s.fresh_within_s}");
    // No fabricated limit when an older backend does not report one.
    expect(t).toContain("Fresh: not reported by this backend.");
    // WireGuard's constant is the API's to state, not this renderer's.
    expect(t, "the renderer restates REJECT_AFTER_TIME's value").not.toMatch(/\b180\b/);
  });

  it("says in the panel that a recent handshake, not the PSK line, is the evidence", () => {
    expect(norm(code(VPN))).toContain("A recent handshake is the evidence of keying; a set PSK is not.");
    expect(norm(code(VPN))).not.toContain("A handshake is the evidence of keying");
  });
});

describe("the Rosenpass exchange is described with one initiator", () => {
  // Only the node with the lower wg0 address is given the peer's wg0 address
  // as its Rosenpass endpoint; the other end answers. With an endpoint on both
  // ends, every cold start left the two ends on different wg1 PSKs.
  it("/vpn names the initiator", () => {
    expect(norm(code(VPN))).toContain(
      "the node with the lower wg0 address initiates it; the other end answers");
  });

  // "Each end", "both nodes", "the two sides": any subject that puts the
  // endpoint on both ends. The possessive comes as JSX writes it (&apos;) or
  // as typed (' or the typographic apostrophe), and "its" or "their", with
  // room for a word such as "Rosenpass" before "endpoint".
  const BOTH_ENDS = String.raw`(?:each (?:end|node|side)|both (?:ends|nodes|sides)|(?:the )?two (?:ends|nodes|sides))`;
  const APOS = String.raw`(?:'|&apos;|\u2019)`;
  const PEERS = String.raw`(?:(?:the )?peer${APOS}s|each other${APOS}s)`;
  const ENDPOINT_ON_BOTH = new RegExp(
    String.raw`${BOTH_ENDS}[^.]{0,80}${PEERS} wg0 address as (?:its|their)(?: [^.\s]+){0,2} endpoint`, "i");
  // Within a sentence about the Rosenpass exchange or wg1: no subject that
  // makes both ends initiators.
  const BOTH_INITIATE = new RegExp(
    String.raw`(?:\bboth\b|${BOTH_ENDS})[^.]{0,60}\binitiat(?:e|es|ing|or|ors)\b`, "i");
  const rosenpassSentences = (t: string) =>
    t.split(/(?<=\.)\s+/).filter((sentence) => /Rosenpass|wg1/i.test(sentence));

  it("the guards catch the overclaims they exist for", () => {
    for (const bad of [
      "each end has the peer's wg0 address as its endpoint",
      "Each node has the peer&apos;s wg0 address as its endpoint",
      "both ends have the peer's wg0 address as their Rosenpass endpoint",
      "Both nodes use each other\u2019s wg0 address as their endpoint",
      "the two sides take the peer's wg0 address as their endpoint",
    ]) {
      expect(bad, bad).toMatch(ENDPOINT_ON_BOTH);
    }
    for (const bad of [
      "In the Rosenpass exchange both nodes initiate.",
      "Both ends initiate the Rosenpass exchange over wg0.",
      "each side initiates the wg1 key exchange.",
    ]) {
      expect(rosenpassSentences(bad).some((x) => BOTH_INITIATE.test(x)), bad).toBe(true);
    }
    // And they leave the sentence /vpn does say alone.
    const ok = "the Rosenpass exchange itself also runs over wg0 (the node with "
      + "the lower wg0 address initiates it; the other end answers)";
    expect(ok).not.toMatch(ENDPOINT_ON_BOTH);
    expect(rosenpassSentences(ok).some((x) => BOTH_INITIATE.test(x))).toBe(false);
  });

  for (const rel of LIVE_PAGES) {
    it(`${rel} does not put the Rosenpass endpoint, or the initiation, on both ends`, () => {
      const t = norm(code(read(rel)));
      expect(t).not.toMatch(ENDPOINT_ON_BOTH);
      for (const sentence of rosenpassSentences(t)) {
        expect(sentence, "a sentence makes both ends initiate").not.toMatch(BOTH_INITIATE);
      }
    });
  }
});

describe("the pin is an unmerged PR head, and no fix is claimed", () => {
  for (const [name, text] of [["Overview.tsx", OVERVIEW], ["VpnProtocols.tsx", VPN]] as const) {
    it(`${name} says so`, () => {
      const t = norm(code(text));
      expect(t).toMatch(/pull request #51, which is still open/);
      expect(t).toContain("f4cf9ba");
      expect(t).toMatch(/re-pinned to the merge commit once #51 merges/);
    });
  }

  it("no source file says the rotation-ordering commit fixes or closes the mismatch", () => {
    // Code reading suggests it moves the exposed intervals from one role to
    // the other; that is not measured. Any mention must not claim a fix.
    const files: string[] = [];
    const walk = (dir: string) => {
      for (const f of readdirSync(dir)) {
        const p = join(dir, f);
        if (statSync(p).isDirectory()) walk(p);
        else if (/\.(ts|tsx)$/.test(f) && !/\.test\.ts$/.test(f)) files.push(p);
      }
    };
    walk(SRC_DIR);
    for (const p of files) {
      expect(readFileSync(p, "utf8"), p)
        .not.toMatch(/3e02741[^.]*\b(fix(es|ed)?|clos(e|es|ed))\b/i);
    }
  });
});

describe("the version is one number across the web UI", () => {
  const pkg = JSON.parse(read("../package.json"));
  const lock = JSON.parse(read("../package-lock.json"));

  it("package-lock.json carries package.json's version", () => {
    expect(lock.version).toBe(pkg.version);
    expect(lock.packages[""].version).toBe(pkg.version);
  });

  it("the backend reports the same release", () => {
    // main.py's FastAPI app version is shown at /docs and in /openapi.json.
    const main = read("../../webui-backend/app/main.py");
    const m = /FastAPI\([^)]*version="([^"]+)"/.exec(main);
    expect(m, "the FastAPI(...) call moved").not.toBeNull();
    expect(m![1]).toBe(pkg.version);
  });
});
