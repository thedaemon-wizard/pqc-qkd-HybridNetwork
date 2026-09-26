/**
 * The /keyflow Sankey must draw the derivation the page claims it draws.
 *
 * As three parallel arrays inline in KeyFlow.tsx it did not. Reading them the
 * way Plotly does:
 *
 *   source: [0, 1, 2, 3, 4, 5, 3, 5]
 *   target: [1, 2, 3, 6, 5, 6, 6, 6]
 *   value:  [200, 120, 100, 32, 256, 32, 32, 32]
 *
 *   * node 7 ("WireGuard PSK") appeared in neither array. The one edge the
 *     page's own sentence promises was the only edge never drawn, and total
 *     flow OUT of the HKDF node was 0.
 *   * (3,6) appeared at indices 3 and 6; (5,6) at 5 and 7. Both HKDF inputs
 *     were drawn twice, so 128 units entered a node emitting 64.
 *   * 200/120/100/256 are bit counts; the four links into HKDF carried 32, the
 *     BYTE count of the same keys.
 *
 * None of that could fail. A missing edge renders as a node with no line
 * attached, which reads as a layout quirk; a duplicated edge just makes a band
 * thicker. Nothing compared the picture to the sentence above it.
 *
 * These tests are structural, so they hold whatever the widths become.
 *
 * Release 0.2.0 moved Rosenpass out of the derivation: the HKDF's PQC input is
 * now the PQC-HPKE key arnika agrees with its peer, and Rosenpass keys wg1, the
 * data tunnel inside wg0. The last block below pins that the two never meet.
 */
import { describe, expect, it } from "vitest";

import {
  KEY_FLOW_COLORS, KEY_FLOW_EDGES, KEY_FLOW_LABELS, KEY_FLOW_NODES, toSankeyLinks,
} from "./keyFlowGraph";

const HKDF = "HKDF-SHA3-256";
const PSK = "wg0 PSK (256 b)";
const WG1_PSK = "wg1 PSK (256 b)";
const ROSENPASS = "Rosenpass McEliece+Kyber512";
const HPKE = "PQC-HPKE MLKEM1024-P384";

describe("the graph is connected", () => {
  it("every node is on at least one edge", () => {
    const used = new Set(KEY_FLOW_EDGES.flatMap((e) => [e.from, e.to]));
    const orphans = KEY_FLOW_NODES.filter((n) => !used.has(n));
    expect(orphans, "a node drawn with no edge reads as a layout quirk").toEqual([]);
  });

  it("the PSK node has an incoming edge -- the one that used to be missing", () => {
    const into = KEY_FLOW_EDGES.filter((e) => e.to === PSK);
    expect(into).toHaveLength(1);
    expect(into[0].from).toBe(HKDF);
  });

  it("every node except the sources and the sinks has both an in and an out edge", () => {
    for (const n of KEY_FLOW_NODES) {
      const isSource = n === "BB84 raw bits" || n === HPKE || n === ROSENPASS;
      const isSink = n === PSK || n === WG1_PSK;
      if (isSource || isSink) continue;
      expect(KEY_FLOW_EDGES.some((e) => e.to === n), `${n} has no input`).toBe(true);
      expect(KEY_FLOW_EDGES.some((e) => e.from === n), `${n} has no output`).toBe(true);
    }
  });
});

describe("no edge is drawn twice", () => {
  it("each (from, to) pair appears exactly once", () => {
    const seen = new Map<string, number>();
    for (const e of KEY_FLOW_EDGES) {
      const k = `${e.from} -> ${e.to}`;
      seen.set(k, (seen.get(k) ?? 0) + 1);
    }
    const dupes = [...seen].filter(([, n]) => n > 1);
    expect(dupes, "a duplicated edge silently doubles a band's width").toEqual([]);
  });
});

describe("the HKDF node narrows, and by the right amount", () => {
  it("takes two 256-bit inputs and emits one 256-bit key", () => {
    const into = KEY_FLOW_EDGES.filter((e) => e.to === HKDF);
    const outOf = KEY_FLOW_EDGES.filter((e) => e.from === HKDF);

    expect(into.map((e) => e.from).sort())
      .toEqual(["PQC key (256 b)", "QKD key (256 b)"]);
    expect(into.reduce((a, e) => a + e.bits, 0)).toBe(512);

    expect(outOf).toHaveLength(1);
    expect(outOf[0].bits).toBe(256);
    // The narrowing IS the derivation. If these ever match, the figure has
    // stopped showing a key-derivation step.
    expect(outOf[0].bits).toBeLessThan(into.reduce((a, e) => a + e.bits, 0));
  });
});

describe("units are bits throughout", () => {
  it("no edge carries a byte count where its neighbours carry bits", () => {
    // 32 was the byte count of a 256-bit key, sitting beside 200/120/100/256.
    // Any edge into or out of a node whose LABEL states a bit width must match
    // that width -- which is what catches a unit slip rather than a magic list.
    for (const e of KEY_FLOW_EDGES) {
      const m = /\((\d+) b\)/.exec(e.to);
      if (m) {
        expect(e.bits, `${e.from} -> ${e.to} disagrees with the node's own label`)
          .toBe(Number(m[1]));
      }
    }
  });

  it("nothing carries 32, the byte count that used to be mixed in", () => {
    expect(KEY_FLOW_EDGES.map((e) => e.bits)).not.toContain(32);
  });
});

describe("illustrative widths are marked as such", () => {
  it("the pre-key stages are flagged and the key material is not", () => {
    const illustrative = KEY_FLOW_EDGES.filter((e) => e.illustrative).map((e) => e.to);
    expect(illustrative).toContain("Sifted (basis-match)");
    // Everything from the derivation rightwards is real key material.
    for (const e of KEY_FLOW_EDGES) {
      if (e.from === HKDF || e.to === HKDF) {
        expect(e.illustrative, `${e.from} -> ${e.to} must not be illustrative`)
          .toBeFalsy();
      }
    }
  });
});

describe("the Plotly arrays are built from the edge list", () => {
  it("indices resolve and the three arrays stay the same length", () => {
    const { source, target, value } = toSankeyLinks();
    expect(source).toHaveLength(KEY_FLOW_EDGES.length);
    expect(target).toHaveLength(KEY_FLOW_EDGES.length);
    expect(value).toHaveLength(KEY_FLOW_EDGES.length);
    for (const i of [...source, ...target]) {
      expect(i).toBeGreaterThanOrEqual(0);
      expect(i).toBeLessThan(KEY_FLOW_NODES.length);
    }
  });

  it("throws on an unknown node rather than emitting -1", () => {
    // Plotly reads -1 as a node index and draws something; the old inline form
    // had no way to notice. This is the failure mode the builder replaces.
    expect(() => toSankeyLinks([
      { from: "nope" as never, to: PSK, bits: 256 },
    ])).toThrow(/unknown keyflow node/);
  });
});

describe("display labels stay in step with node ids", () => {
  it("every node has a label", () => {
    for (const n of KEY_FLOW_NODES) {
      expect(KEY_FLOW_LABELS[n], `${n} has no display label`).toBeTruthy();
    }
    expect(Object.keys(KEY_FLOW_LABELS).sort()).toEqual([...KEY_FLOW_NODES].sort());
  });

  it("the measured collisions are shortened, and only those", () => {
    // Measured on the deployed page: with the full names, "HKDF-SHA3-256" and
    // the PSK sink ("WireGuard PSK (256 b)" then) render on top of each other.
    // Shortening either one alone does not clear it; a right margin does
    // nothing at 0, 40 or 150 px. Both sinks now sit in that terminal column,
    // so both keep the short form. The PQC-HPKE source's full name ran into
    // the column-1 node beside it (measured 2026-09-26). Pinned so a future
    // edit that restores the long labels has to re-measure rather than
    // reintroduce the collision.
    const SHORT: Record<string, string> = {
      [HKDF]: "HKDF", [PSK]: "wg0 PSK", [WG1_PSK]: "wg1 PSK", [HPKE]: "PQC-HPKE",
    };
    for (const n of KEY_FLOW_NODES) {
      expect(KEY_FLOW_LABELS[n], `${n} was shortened without cause`).toBe(SHORT[n] ?? n);
    }
  });

  it("the units check still reads the ID, not the shortened label", () => {
    // The `(256 b)` the unit test keys off lives in the id. If a future change
    // moved that check onto the display label it would silently stop checking
    // the two shortened nodes -- which are the two the derivation runs through.
    const idsWithWidth = KEY_FLOW_NODES.filter((n) => /\(\d+ b\)/.test(n));
    expect(idsWithWidth).toContain(PSK);
    expect(idsWithWidth).toContain(WG1_PSK);
    expect(idsWithWidth.length).toBeGreaterThanOrEqual(3);
  });
});

describe("Rosenpass keys wg1 and never enters the derivation", () => {
  it("the HKDF's PQC input comes from PQC-HPKE, not from Rosenpass", () => {
    const pqcFrom = KEY_FLOW_EDGES.filter((e) => e.to === "PQC key (256 b)").map((e) => e.from);
    expect(pqcFrom).toEqual([HPKE]);
  });

  it("Rosenpass has exactly one edge, into wg1's PSK", () => {
    const touching = KEY_FLOW_EDGES.filter((e) => e.from === ROSENPASS || e.to === ROSENPASS);
    expect(touching).toEqual([{ from: ROSENPASS, to: WG1_PSK, bits: 256 }]);
  });

  it("nothing reachable from Rosenpass reaches the HKDF, and the reverse", () => {
    // Walk the edges from each source. If a later edit wires Rosenpass into
    // any node on the derivation path, its reach grows to include the HKDF.
    const reach = (start: string) => {
      const seen = new Set([start]);
      const todo = [start];
      while (todo.length) {
        const n = todo.pop()!;
        for (const e of KEY_FLOW_EDGES) {
          if (e.from === n && !seen.has(e.to)) { seen.add(e.to); todo.push(e.to); }
        }
      }
      return seen;
    };
    expect([...reach(ROSENPASS)].sort()).toEqual([ROSENPASS, WG1_PSK].sort());
    expect(reach(HPKE).has(WG1_PSK)).toBe(false);
    expect(reach("BB84 raw bits").has(WG1_PSK)).toBe(false);
    expect(reach(HPKE).has(PSK)).toBe(true);
  });

  it("names the HPKE suite as the registry writes it", () => {
    // MLKEM1024-P384 is the HPKE KEM name in arnika's pqchpke package and in
    // draft-ietf-hpke-pq. Its hyphen placement differs from "ML-KEM-1024" on
    // purpose: it names the hybrid KEM, not ML-KEM alone. It is in the node
    // id, which the JSON export carries; the chart prints the short label.
    expect(KEY_FLOW_NODES).toContain(HPKE);
    expect(HPKE).toContain("MLKEM1024-P384");
  });
});

describe("colours are keyed by node", () => {
  it("every node has a colour, and nothing else does", () => {
    expect(Object.keys(KEY_FLOW_COLORS).sort()).toEqual([...KEY_FLOW_NODES].sort());
  });

  it("the two components do not share a source colour", () => {
    // Links take their source's colour, so this is what keeps the Rosenpass
    // band visibly apart from the PQC-HPKE band on the page.
    expect(KEY_FLOW_COLORS[ROSENPASS]).not.toBe(KEY_FLOW_COLORS[HPKE]);
    expect(KEY_FLOW_COLORS[ROSENPASS]).not.toBe(KEY_FLOW_COLORS["BB84 raw bits"]);
  });
});
