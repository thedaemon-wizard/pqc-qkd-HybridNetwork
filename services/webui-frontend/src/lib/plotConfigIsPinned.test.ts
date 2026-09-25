/**
 * Every <Plot> takes PLOT_CONFIG, and PLOT_CONFIG keeps the cloud button off.
 *
 * plotly.js 4 defaults `showSendToCloud` to true (see plotConfig.ts). A chart
 * written with an inline `config={{ displaylogo: false }}` -- the shape every
 * chart here had before -- silently gets a button that uploads its data to
 * cloud.plotly.com. Asserted on the source: the property is "no chart is
 * configured anywhere else", which a render of one page cannot show.
 */
import { describe, expect, it } from "vitest";

import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";

import { PLOT_CONFIG } from "./plotConfig";

const SRC_DIR = join(new URL(".", import.meta.url).pathname, "..");

function sourceFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) return sourceFiles(p);
    return /\.tsx?$/.test(name) && !/\.test\.tsx?$/.test(name) ? [p] : [];
  });
}

/** Each `<Plot ... />` element's attribute text, per file. */
function plotElements(): { file: string; attrs: string }[] {
  return sourceFiles(SRC_DIR).flatMap((file) => {
    const src = readFileSync(file, "utf8");
    return [...src.matchAll(/<Plot\b([\s\S]*?)\/>/g)].map((m) => ({ file, attrs: m[1] }));
  });
}

describe("Plotly config", () => {
  it("keeps the send-to-cloud button off", () => {
    expect(PLOT_CONFIG.showSendToCloud).toBe(false);
    expect(PLOT_CONFIG.displaylogo).toBe(false);
  });

  it("finds the charts it is guarding", () => {
    // Guard the guard: a regex that matched nothing would pass the next test.
    expect(plotElements().length).toBeGreaterThanOrEqual(5);
  });

  it("gives every <Plot> the shared config and nothing else", () => {
    const off = plotElements().filter(({ attrs }) => !/\bconfig=\{PLOT_CONFIG\}/.test(attrs));
    expect(off.map(({ file }) => file)).toEqual([]);
  });
});
