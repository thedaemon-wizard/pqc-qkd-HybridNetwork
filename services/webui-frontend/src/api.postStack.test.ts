/**
 * A refused container action must not resolve.
 *
 * `postStack` was:
 *
 *     const r = await fetch(...);
 *     return r.json();
 *
 * FastAPI's HTTPException body is valid JSON, so a 403 RESOLVED with
 * `{detail: "container control is disabled; ..."}`. The call site was
 * `onClick={() => postStack("restart", s.name)}` -- the promise discarded --
 * so a refused restart produced no state change, no console entry, and not
 * even an unhandled rejection. It was visually indistinguishable from one that
 * worked.
 *
 * Measured on the public demo, 2026-08-27:
 *
 *     /api/config          -> {"demo_mode":false,"container_control":false}
 *     /api/stack           -> 10 containers
 *     the Overview page    -> 10 restart buttons rendered
 *     POST /api/stack/restart/<name> -> 403
 *
 * The button was rendered because it was gated on `!demo_mode` while the
 * endpoint is gated on `container_control`, and those disagree in exactly the
 * configuration the demo runs. `useContainerControl` already existed for this,
 * with a doc comment saying so; the page had not adopted it.
 */
import { afterEach, describe, expect, it, vi } from "vitest";

import { postStack } from "./api";

function mockFetch(status: number, body: unknown) {
  return vi.fn(async () => ({
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  })) as unknown as typeof fetch;
}

afterEach(() => { vi.unstubAllGlobals(); });

describe("postStack surfaces what the server said", () => {
  it("rejects on 403 and carries the detail through", async () => {
    const detail = "container control is disabled; set ENABLE_CONTAINER_CONTROL=1 "
      + "(and do not set DEMO_MODE) on a trusted host to enable it";
    vi.stubGlobal("fetch", mockFetch(403, { detail }));

    await expect(postStack("restart", "alice")).rejects.toThrow(/container control is disabled/);
  });

  it("rejects on 500 even though the body is valid JSON", async () => {
    // The shape that made this invisible: an error body that parses fine.
    vi.stubGlobal("fetch", mockFetch(500, { detail: "docker not available" }));
    await expect(postStack("restart", "alice")).rejects.toThrow(/docker not available/);
  });

  it("rejects on an error with no body at all", async () => {
    // A proxy 502 in front of the backend returns no JSON; `.json()` throws.
    vi.stubGlobal("fetch", vi.fn(async () => ({
      ok: false, status: 502, json: async () => { throw new SyntaxError("not json"); },
    })) as unknown as typeof fetch);

    await expect(postStack("restart", "alice")).rejects.toThrow(/HTTP 502/);
  });

  it("still resolves with the body on success", async () => {
    // The other direction: "always throw" would be the same defect inverted.
    vi.stubGlobal("fetch", mockFetch(200, { ok: true, name: "alice" }));
    await expect(postStack("restart", "alice")).resolves.toEqual({ ok: true, name: "alice" });
  });

  it("hits the /{action}/{name} route, not /{action} with a body", async () => {
    // scripts/verify-demo-hardening.sh probed the wrong shape for months and
    // passed on the resulting 404; pin the path here too.
    const f = mockFetch(200, {});
    vi.stubGlobal("fetch", f);
    await postStack("stop", "bob");
    const [url, init] = (f as unknown as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(String(url)).toMatch(/\/api\/stack\/stop\/bob$/);
    expect((init as RequestInit).method).toBe("POST");
  });
});
