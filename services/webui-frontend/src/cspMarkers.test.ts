/**
 * The two markers in index.html keep plotly.js from inserting inline <style>s.
 *
 * deploy/Caddyfile sends a Content-Security-Policy that allows one inline
 * <style>, the block in index.html, by its hash. The bundled plotly.js
 * (react-plotly.js loads `plotly.js/dist/plotly.js`) inserts two more at
 * start-up, on every route, unless two elements exist first:
 *
 *   - `#plotly.js-style-global.no-inline-styles`: lib/dom.js returns before
 *     creating its stylesheet. Its rules then come from dist/plotly.css, which
 *     src/main.tsx imports, so the build serves them as a file;
 *   - an element whose id is the one the bundle's maplibre-gl CSS block looks
 *     up. That id is not documented anywhere, so it is read out of the bundle
 *     here: an upgrade that changes it fails this file, not the live site.
 *
 * The maplibre rules are only for map charts, and none is drawn here; the last
 * case pins that, because a map chart added later would need them.
 *
 * Read from the files, like the other source guards here. Whether a browser
 * then reports no violation is scripts/csp_smoke.py, which CI runs on the build.
 */
import { describe, expect, it } from "vitest";

import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";

const HERE = new URL(".", import.meta.url).pathname;
const ROOT = join(HERE, "..");
const INDEX = readFileSync(join(ROOT, "index.html"), "utf8");
const MAIN = readFileSync(join(HERE, "main.tsx"), "utf8");
const PLOTLY = readFileSync(join(ROOT, "node_modules/plotly.js/dist/plotly.js"), "utf8");

/** Opening tags inside index.html's body, comments removed. */
function bodyTags(): string[] {
  const body = INDEX.slice(INDEX.indexOf("<body>") + "<body>".length).replace(/<!--[\s\S]*?-->/g, "");
  return [...body.matchAll(/<[a-z][^>]*>/g)].map((m) => m[0]);
}

function sourceFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) return sourceFiles(p);
    return /\.tsx?$/.test(name) && !/\.test\.tsx?$/.test(name) ? [p] : [];
  });
}

describe("CSP markers for plotly.js", () => {
  it("has the marker plotly.js checks before inserting its stylesheet", () => {
    expect(PLOTLY).toContain('matches(".no-inline-styles")');
    expect(PLOTLY).toContain('"plotly.js-style-" + uid');
    expect(bodyTags()).toContain('<div id="plotly.js-style-global" class="no-inline-styles" hidden>');
  });

  it("imports plotly.js's stylesheet in place of the inline rules", () => {
    expect(MAIN).toMatch(/^import "plotly\.js\/dist\/plotly\.css";$/m);
    expect(readFileSync(join(ROOT, "node_modules/plotly.js/dist/plotly.css"), "utf8")).toContain(".modebar");
  });

  it("has an element with the id the maplibre-gl CSS block looks up", () => {
    const block = PLOTLY.indexOf('"node_modules/maplibre-gl/dist/maplibre-gl.css"()');
    expect(block).toBeGreaterThan(0);
    const lookup = /document\.getElementById\("([0-9a-f]{64})"\)/.exec(PLOTLY.slice(block, block + 600));
    expect(lookup).not.toBeNull();
    expect(bodyTags()).toContain(`<div id="${lookup![1]}" hidden>`);
  });

  it("keeps the markers out of the React root and before the script", () => {
    const tags = bodyTags();
    const root = tags.indexOf('<div id="root">');
    expect(root).toBeGreaterThan(1);
    expect(tags.slice(0, root).every((t) => t.endsWith(" hidden>"))).toBe(true);
    expect(tags.findIndex((t) => t.startsWith("<script"))).toBeGreaterThan(root);
  });

  it("draws no map chart, so the maplibre rules are not needed", () => {
    const mapTraces = /\b(scattermap|scattermapbox|choroplethmap|choroplethmapbox|densitymap|densitymapbox)\b/;
    const users = sourceFiles(HERE).filter((f) => mapTraces.test(readFileSync(f, "utf8")));
    expect(users).toEqual([]);
  });
});
