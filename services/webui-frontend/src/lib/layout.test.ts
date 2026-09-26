/**
 * The shell has one breakpoint, and it is the number the layout was measured
 * against.
 *
 * At 375px the 220px sidebar left <main> 155px and 13 of 14 routes scrolled
 * sideways; at 768px none did (measured 2026-09-26). So the collapsed shell is
 * for viewports up to 767px, and a 768px tablet keeps the sidebar. The media
 * query is built from that constant, and no other source file carries a
 * breakpoint of its own: two breakpoints a few pixels apart would leave a band
 * of widths where the sidebar is gone but a page's panels are still side by
 * side, or the reverse.
 */
import { describe, expect, it, vi } from "vitest";

import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";

import {
  NARROW_COLUMN, NARROW_LAYOUT_MAX_PX, NARROW_LAYOUT_QUERY, NARROW_MAIN_PADDING,
  createNarrowLayoutStore, narrowColumns, readNarrowLayout, subscribeNarrowLayout,
  type MediaQuerySource,
} from "./layout";

describe("the breakpoint", () => {
  it("is 767px: a 768px tablet keeps the sidebar", () => {
    expect(NARROW_LAYOUT_MAX_PX).toBe(767);
  });

  it("the media query is derived from NARROW_LAYOUT_MAX_PX", () => {
    expect(NARROW_LAYOUT_QUERY).toBe(`(max-width: ${NARROW_LAYOUT_MAX_PX}px)`);
    const src = readFileSync(new URL("./layout.ts", import.meta.url), "utf8");
    // Built from the constant, not a second literal that could drift from it.
    expect(src).toMatch(/NARROW_LAYOUT_QUERY = `\(max-width: \$\{NARROW_LAYOUT_MAX_PX\}px\)`/);
  });

  it("the narrow <main> padding is a named 16px gutter", () => {
    expect(NARROW_MAIN_PADDING).toBe("1rem");
  });
});

describe("narrowColumns", () => {
  it("is one shrinkable column when narrow", () => {
    expect(narrowColumns(true, "1fr 1fr")).toBe("minmax(0, 1fr)");
    expect(NARROW_COLUMN).toBe("minmax(0, 1fr)");
  });

  it("returns the page's own template unchanged otherwise", () => {
    for (const wide of ["1fr 1fr", "repeat(5, 1fr)", "220px 1fr", "2fr 1fr"]) {
      expect(narrowColumns(false, wide)).toBe(wide);
    }
  });
});

/** A window stand-in whose one MediaQueryList records its listeners. */
function fakeWindow(matches: boolean) {
  const queries: string[] = [];
  const listeners = new Set<() => void>();
  const list = {
    matches,
    addEventListener: vi.fn((_t: "change", cb: () => void) => { listeners.add(cb); }),
    removeEventListener: vi.fn((_t: "change", cb: () => void) => { listeners.delete(cb); }),
  };
  const source: MediaQuerySource = {
    matchMedia: (q: string) => { queries.push(q); return list; },
  };
  return { source, list, queries, listeners };
}

describe("reading and following the media query", () => {
  it("reports whether the list matches", () => {
    expect(readNarrowLayout(fakeWindow(true).list)).toBe(true);
    expect(readNarrowLayout(fakeWindow(false).list)).toBe(false);
  });

  it("listens for changes and stops listening on the same list", () => {
    const w = fakeWindow(false);
    const onChange = () => {};
    const stop = subscribeNarrowLayout(w.list, onChange);
    expect(w.listeners.has(onChange)).toBe(true);
    stop();
    expect(w.listeners.size).toBe(0);
    expect(w.list.removeEventListener).toHaveBeenCalledWith("change", onChange);
  });
});

describe("one MediaQueryList, shared by the snapshot and the subscriptions", () => {
  it("is not created until it is first used", () => {
    const w = fakeWindow(false);
    const source = vi.fn(() => w.source);
    createNarrowLayoutStore(source);
    // Importing lib/layout.ts must not touch `window`: node has none.
    expect(source).not.toHaveBeenCalled();
    expect(w.queries).toEqual([]);
  });

  it("is created once, for NARROW_LAYOUT_QUERY, however often it is read", () => {
    const w = fakeWindow(true);
    const store = createNarrowLayoutStore(() => w.source);
    // Every Panel and KPI reads the snapshot on every render.
    for (let i = 0; i < 5; i++) expect(store.getSnapshot()).toBe(true);
    const stops = [store.subscribe(() => {}), store.subscribe(() => {})];
    expect(w.queries).toEqual([NARROW_LAYOUT_QUERY]);
    expect(w.listeners.size).toBe(2);
    for (const stop of stops) stop();
    expect(w.listeners.size).toBe(0);
  });

  it("the snapshot follows the list when the viewport crosses the breakpoint", () => {
    const w = fakeWindow(false);
    const store = createNarrowLayoutStore(() => w.source);
    let changes = 0;
    store.subscribe(() => { changes += 1; });
    expect(store.getSnapshot()).toBe(false);
    w.list.matches = true;
    for (const cb of w.listeners) cb();
    expect(changes).toBe(1);
    expect(store.getSnapshot()).toBe(true);
  });

  it("useNarrowLayout uses the one module-level store, created from a function of window", () => {
    const src = readFileSync(new URL("./layout.ts", import.meta.url), "utf8")
      .replace(/\/\*[\s\S]*?\*\//g, "").replace(/(?<!:)\/\/[^\n]*/g, "");
    // `() => window`, not `window`: evaluated on first use, not at import.
    expect(src).toMatch(/const store = createNarrowLayoutStore\(\(\) => window\);/);
    expect(src).toMatch(/useSyncExternalStore\(store\.subscribe, store\.getSnapshot, getServerSnapshot\)/);
    // One call site, inside the store's lazy getter.
    expect(src.match(/\.matchMedia\(/g)).toHaveLength(1);
    expect(src).toMatch(/list \?\?= source\(\)\.matchMedia\(NARROW_LAYOUT_QUERY\)/);
  });
});

describe("no other file has a breakpoint of its own", () => {
  const SRC = join(new URL(".", import.meta.url).pathname, "..");
  const files: string[] = [];
  const walk = (dir: string) => {
    for (const name of readdirSync(dir)) {
      const p = join(dir, name);
      if (statSync(p).isDirectory()) walk(p);
      else if (/\.tsx?$/.test(name) && !/\.test\.tsx?$/.test(name)) files.push(p);
    }
  };
  walk(SRC);
  /** Code without comments, which may describe widths in prose. */
  const code = (s: string) => s.replace(/\/\*[\s\S]*?\*\//g, "").replace(/(?<!:)\/\/[^\n]*/g, "");

  it("finds the source files", () => {
    expect(files.length, "the walk found nothing; this test is now vacuous").toBeGreaterThan(20);
  });

  for (const file of files) {
    const rel = relative(SRC, file);
    if (rel === join("lib", "layout.ts")) continue;
    it(`${rel} asks lib/layout.ts instead of querying the viewport width`, () => {
      const text = code(readFileSync(file, "utf8"));
      expect(text).not.toMatch(/matchMedia\s*\(/);
      expect(text).not.toMatch(/@media\b/);
      expect(text).not.toMatch(/\((?:max|min)-width\s*:/);
    });
  }
});
