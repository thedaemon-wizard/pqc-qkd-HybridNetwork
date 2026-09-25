/**
 * /physics must not change shared server state unless the host allows it.
 *
 * `POST /api/sim/params`, `/api/sim/params/reset` and `/api/sim/backend` change
 * process-global state on both KMEs, which also feed the live VPN lanes. On a
 * shared host one visitor's edit became every visitor's, last write winning.
 * The backend now refuses the three routes unless ENABLE_LIVE_PARAM_OVERRIDES
 * is set, and reports the flag as `live_param_overrides` in /api/config. This
 * page reads that flag and, when it is false, keeps Apply and Reset in the
 * browser and disables the backend switch with the reason on screen.
 *
 * Two further defects on the same page:
 *   - a switch the KMEs refused was reported as "requested", because the
 *     fan-out answers HTTP 200 with `ok: false` and only `r.ok` was read;
 *   - the two backends that forward to `qkdnetsim-kme` were offered on a host
 *     where that container does not run, and one click left every round on
 *     both KMEs failing.
 */
import { describe, expect, it } from "vitest";

import { readFileSync } from "node:fs";
import { join } from "node:path";

const HERE = new URL(".", import.meta.url).pathname;
const PAGE = readFileSync(join(HERE, "PhysicsParams.tsx"), "utf8");
const CONFIG = readFileSync(join(HERE, "../lib/useConfig.ts"), "utf8");
const API = readFileSync(join(HERE, "../api.ts"), "utf8");

/** The body of `async function <name>(`, up to the next top-level function. */
function body(name: string): string {
  const start = PAGE.indexOf(`async function ${name}(`);
  expect(start, `${name} is gone`).toBeGreaterThan(-1);
  const rest = PAGE.slice(start + 1);
  const next = rest.search(/\n  (async )?function /);
  return next === -1 ? rest : rest.slice(0, next);
}

describe("the config flag", () => {
  it("is part of the /api/config type", () => {
    expect(API).toMatch(/live_param_overrides: boolean;/);
  });

  it("fails closed: the restrictive default says overrides are off", () => {
    expect(CONFIG).toMatch(/live_param_overrides: false/);
    expect(CONFIG).toMatch(/live_param_overrides === true/);
  });

  it("is what the page reads", () => {
    expect(PAGE).toContain("useLiveParamOverrides()");
  });
});

describe("with live overrides off, nothing is sent", () => {
  for (const fn of ["applyEdits", "resetParams"]) {
    it(`${fn} returns before any request`, () => {
      const b = body(fn);
      const local = b.indexOf("if (!live)");
      expect(local, `${fn} has no local branch`).toBeGreaterThan(-1);
      const branch = b.slice(local, b.indexOf("return;", local));
      expect(branch).not.toContain("fetch(");
      expect(local).toBeLessThan(b.indexOf("fetch("));
    });
  }

  it("the backend buttons are disabled and say why", () => {
    expect(PAGE).toMatch(/const off = busy \|\| !live \|\|/);
    expect(PAGE).toContain("Switching is disabled: {LOCAL_ONLY_REASON}");
  });

  it("the reason matches the backend's 403 detail word for word", () => {
    expect(PAGE).toContain(
      "live parameter overrides are disabled on this host (ENABLE_LIVE_PARAM_OVERRIDES=false); edits apply to the in-browser model only");
  });

  it("the page says so in text, not only in a tooltip", () => {
    expect(PAGE).toContain("Not sent to the server: {LOCAL_ONLY_REASON}.");
    expect(PAGE).toContain("in-browser edits active (not sent to the KMEs)");
  });
});

describe("a fan-out answer is read, not just its HTTP status", () => {
  it("success requires body.ok === true", () => {
    expect(PAGE).toMatch(/if \(r\.ok && body\?\.ok === true\) return null;/);
  });

  for (const fn of ["applyEdits", "resetParams", "switchBackend"]) {
    it(`${fn} goes through fanoutFailure`, () => {
      expect(body(fn)).toContain("fanoutFailure(r, body)");
    });
  }

  it("no success message is keyed on r.ok alone", () => {
    expect(PAGE).not.toMatch(/r\.ok \? `Backend switch/);
    expect(PAGE).not.toContain("switch to ${name} requested");
  });

  it("a missing count is said to be missing, not assumed to be two", () => {
    expect(PAGE).not.toMatch(/body\.of \?\? 2/);
  });
});

describe("qkdnetsim-dependent backends", () => {
  it("are offered only while qkdnetsim-kme is running", () => {
    expect(PAGE).toMatch(/QKDNETSIM_DEPENDENT: ReadonlySet<string> = new Set\(\["composite_sim_to_net", "qkdnetsim_proxy"\]\)/);
    expect(PAGE).toContain('const qkdnetsimUp = qkdnetsim === "running";');
    expect(PAGE).toMatch(/QKDNETSIM_DEPENDENT\.has\(b\) && !qkdnetsimUp/);
  });

  it("and the reason is visible text", () => {
    expect(PAGE).toMatch(/\{qkdnetsimWhy\}, and both forward every round to it\./);
  });
});

describe("an absent parameter is not zero", () => {
  it("pv() has no numeric fallback", () => {
    expect(PAGE).not.toMatch(/\?\.value \?\? 0\)/);
    expect(PAGE).toContain("Not computed: the backend did not report");
  });
});
