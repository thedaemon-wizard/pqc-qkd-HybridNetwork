/**
 * A page that reports the running stack must be able to say it cannot see it.
 *
 * `/topology` could not. `Topology.tsx` fetched with
 *
 *     useEffect(() => { getTopology().then(setTopo); }, []);
 *
 * and rendered `<div>Loading…</div>` for any falsy `topo`. Two consequences,
 * and the second is the one that matters:
 *
 *   1. The rejection was unhandled. On a static deploy nobody reads the
 *      console, so the only trace of the failure went nowhere.
 *   2. "The backend is down" and "the request is still in flight" rendered
 *      IDENTICALLY, and the first state never left. A visitor sees a spinner
 *      that means nothing and waits.
 *
 * Every other backend-dependent page already had the path -- /vpn renders
 * "-- not observed --", /benchmarks and /console catch and report -- so this
 * was the last one, and `docs/deployment-economics.md` had already listed
 * /topology as "Degrades: no graph data" while the code had no way to degrade.
 *
 * WHY NOT FALL BACK TO A DRAWN GRAPH. `/api/topology` returns a fixed
 * four-node list, so a client-side copy would be easy and would be the wrong
 * fix: an invented graph is pixel-identical to a measured one. That is the
 * defect this repository exists to avoid, and the same reason /vpn,
 * /benchmarks and /console are deliberately not client-side.
 *
 * These assertions read the source rather than mounting React, matching the
 * other page guards in this directory.
 */
import { describe, expect, it } from "vitest";

import { readFileSync } from "node:fs";
import { join } from "node:path";

const HERE = new URL(".", import.meta.url).pathname;
const read = (f: string) => readFileSync(join(HERE, f), "utf8");

const TOPOLOGY = read("Topology.tsx");

/** Pages whose content comes from the backend and cannot be synthesised. */
const BACKEND_PAGES = ["Topology.tsx", "VpnProtocols.tsx", "Benchmarks.tsx", "Console.tsx"];

describe("/topology distinguishes cannot-look from still-looking", () => {
  it("handles the rejection instead of leaving it unhandled", () => {
    expect(TOPOLOGY).toMatch(/getTopology\(\)[\s\S]{0,80}\.catch\(/);
  });

  it("keeps a failure state separate from the absent-data state", () => {
    // A single `topo === null` cannot express both. If the catch only logged,
    // the render below would still be unreachable.
    expect(TOPOLOGY).toMatch(/const \[failed, setFailed\]/);
    expect(TOPOLOGY).toMatch(/setFailed\(/);
  });

  it("renders something that names the failure, not a spinner", () => {
    expect(TOPOLOGY).toMatch(/if \(failed\)/);
    expect(TOPOLOGY).toMatch(/not observed/);
    // And the failure branch must come BEFORE the loading branch, or it is
    // dead. Anchor on the RENDER guard: `if (!topo)` also appears as an early
    // return inside the d3 effect, at a lower index than the failure branch,
    // and matching that one made this assertion fail against correct code.
    expect(TOPOLOGY.indexOf("if (failed)"))
      .toBeLessThan(TOPOLOGY.indexOf("if (!topo) return <div>Loading"));
  });

  it("still has a loading state -- the fix must not remove it", () => {
    // Collapsing the two back into one, in either direction, is the bug again.
    expect(TOPOLOGY).toMatch(/if \(!topo\) return/);
  });

  it("does not synthesise a graph when the backend is absent", () => {
    // The honest failure is the whole point; a bundled fallback graph would
    // pass every assertion above and reintroduce the defect.
    expect(TOPOLOGY, "a hardcoded node list appeared in the failure path")
      .not.toMatch(/if \(failed\)[\s\S]{0,600}nodes:\s*\[/);
  });
});

describe("the other backend pages still have the path", () => {
  // Not vacuous: these are the precedent /topology was measured against, so if
  // one of them loses its path this file should notice rather than /topology
  // silently becoming the only page that behaves.
  it.each(BACKEND_PAGES)("%s reports rather than hanging", (file) => {
    const src = read(file);
    expect(src, `${file} has no catch and no not-observed rendering`)
      .toMatch(/\.catch\(|catch\s*[({]|not observed/);
  });

  it("Benchmarks.tsx handles the fetch rejecting, not only an error field", () => {
    // This test found a second page with the same class of defect, in a
    // different shape. Benchmarks handled "the backend answered but the KME
    // did not" via reading(), and had nothing for "the backend did not
    // answer" -- an unhandled rejection inside a 1 s setInterval, so one
    // console error per second while the page kept showing stale numbers as
    // though they were live.
    const src = read("Benchmarks.tsx");
    expect(src).toMatch(/try \{[\s\S]{0,120}await getStats\(\)/);
    expect(src).toMatch(/setUnreachable\(/);
    expect(src, "the failure is caught but never rendered")
      .toMatch(/\{unreachable &&/);
  });
});
