/**
 * The saved-exports picker offers Delete only where the backend allows it.
 *
 * The gallery is one directory for every visitor of a host, and
 * `DELETE /api/exports/{filename}` let any visitor delete any file in it. The
 * backend now refuses that unless ENABLE_SHARED_EXPORT_DELETE is set, and
 * reports the flag as `shared_export_delete` in /api/config. Pinned here:
 *
 *   - deleteExport rejects a refusal or a failure with the server's detail and
 *     resolves a success. The picker used to `await fetch(...)` and refresh, so
 *     a refused delete looked like a delete that had not happened yet;
 *   - the flag is in the config type and fails closed: an absent or unreachable
 *     backend reads as "not allowed";
 *   - the picker renders Delete only behind the flag, and says why in text, in
 *     the backend's own words;
 *   - remove() goes through deleteExport and shows what went wrong.
 *
 * The component assertions read the source rather than mounting React,
 * matching the other component guards in this directory.
 */
import { afterEach, describe, expect, it, vi } from "vitest";

import { readFileSync } from "node:fs";
import { join } from "node:path";

import { deleteExport } from "../api";
import { DELETE_DISABLED_REASON } from "./SavedExportsPicker";

const HERE = new URL(".", import.meta.url).pathname;
const PICKER = readFileSync(join(HERE, "SavedExportsPicker.tsx"), "utf8");
const CONFIG = readFileSync(join(HERE, "../lib/useConfig.ts"), "utf8");
const API = readFileSync(join(HERE, "../api.ts"), "utf8");

/** The backend's 403 detail (SHARED_EXPORT_DELETE_DISABLED_DETAIL in main.py). */
const BACKEND_DETAIL =
  "deleting saved exports is disabled on this host (ENABLE_SHARED_EXPORT_DELETE=false); "
  + "the gallery is shared by every visitor and drops its oldest files by itself";

function mockFetch(status: number, body: unknown) {
  return vi.fn(async () => ({
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  })) as unknown as typeof fetch;
}

afterEach(() => { vi.unstubAllGlobals(); });

describe("deleteExport surfaces what the server said", () => {
  it("rejects a refusal with the backend's detail", async () => {
    vi.stubGlobal("fetch", mockFetch(403, { detail: BACKEND_DETAIL }));
    await expect(deleteExport("a.png")).rejects.toThrow(/deleting saved exports is disabled/);
  });

  it("rejects a file that is already gone", async () => {
    // Another visitor deleted it first: "not found" is the honest answer, and
    // it must not read as a successful delete.
    vi.stubGlobal("fetch", mockFetch(404, { detail: "not found" }));
    await expect(deleteExport("a.png")).rejects.toThrow(/not found/);
  });

  it("rejects an error with no body at all", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => ({
      ok: false, status: 502, json: async () => { throw new SyntaxError("not json"); },
    })) as unknown as typeof fetch);
    await expect(deleteExport("a.png")).rejects.toThrow(/HTTP 502/);
  });

  it("resolves a delete that happened", async () => {
    // The other direction: "always throw" would be the same defect inverted.
    vi.stubGlobal("fetch", mockFetch(200, { ok: true }));
    await expect(deleteExport("a.png")).resolves.toEqual({ ok: true });
  });

  it("sends DELETE to the encoded name", async () => {
    const f = mockFetch(200, { ok: true });
    vi.stubGlobal("fetch", f);
    await deleteExport("20261012-000000-a b.png");
    const [url, init] = (f as unknown as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(String(url)).toBe("/api/exports/20261012-000000-a%20b.png");
    expect((init as RequestInit).method).toBe("DELETE");
  });
});

describe("the config flag", () => {
  it("is part of the /api/config type", () => {
    expect(API).toMatch(/shared_export_delete: boolean;/);
  });

  it("fails closed", () => {
    expect(CONFIG).toMatch(/shared_export_delete: false/);
    expect(CONFIG).toMatch(/shared_export_delete === true/);
  });
});

describe("the picker", () => {
  it("reads the flag", () => {
    expect(PICKER).toContain("const canDelete = useSharedExportDelete();");
  });

  it("renders the Delete button only behind it", () => {
    expect(PICKER.match(/>Delete<\/Button>/g)?.length,
           "the Delete button is gone, or there are two; re-point this guard").toBe(1);
    // The one button is the whole of the gated expression: the gate opens
    // right before it and closes right after it.
    expect(PICKER).toMatch(/\{canDelete && \(\s*<Button[\s\S]{0,200}?>Delete<\/Button>\s*\)\}/);
  });

  it("says why there is no Delete, in text and in the backend's words", () => {
    expect(DELETE_DISABLED_REASON).toBe(BACKEND_DETAIL);
    expect(PICKER).toMatch(/\{!canDelete && \(/);
    expect(PICKER).toContain("Delete is not offered here: {DELETE_DISABLED_REASON}.");
  });

  it("deletes through deleteExport and shows a failure", () => {
    const start = PICKER.indexOf("async function remove(");
    expect(start).toBeGreaterThan(-1);
    const body = PICKER.slice(start, PICKER.indexOf("\n  }\n", start));
    expect(body).toContain("await deleteExport(name)");
    expect(body).toMatch(/setErr\(`Not deleted: \$\{why\}`\)/);
    // The response is no longer discarded by a bare fetch.
    expect(PICKER).not.toMatch(/method: "DELETE"/);
  });
});
