/**
 * A PNG export must not fetch its own data: URL.
 *
 * The page draws the PNG on a canvas and reads it back as a data: URL. It then
 * turned that into a Blob with `fetch(dataUrl)`, which is a connection: the
 * site's Content-Security-Policy has `connect-src 'self'`, and 'self' does not
 * match data:. So from 2026-11-20, when the policy was enforced, every PNG
 * export drew its image and then failed with "Failed to fetch". Nothing pressed
 * the button under the policy until scripts/spa_tabs_smoke.py did, on
 * 2026-11-25. `dataUrlToBlob` decodes the URL instead, and the policy stays.
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import { dataUrlToBlob } from "./exporters";

const HERE = new URL(".", import.meta.url).pathname;
// The eight bytes every PNG starts with, then a few of an IHDR chunk.
const PNG_HEAD = [0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, 0x00, 0x00, 0x00, 0x0d];

describe("dataUrlToBlob", () => {
  it("gives back the bytes and the type of a base64 data: URL", async () => {
    const url = `data:image/png;base64,${btoa(String.fromCharCode(...PNG_HEAD))}`;
    const blob = dataUrlToBlob(url);
    expect(blob.type).toBe("image/png");
    expect([...new Uint8Array(await blob.arrayBuffer())]).toEqual(PNG_HEAD);
  });

  it("decodes a percent-encoded one too", async () => {
    const blob = dataUrlToBlob("data:text/plain;charset=utf-8,a%2Cb%20%E2%9C%93");
    expect(blob.type).toBe("text/plain");
    expect(await blob.text()).toBe("a,b ✓");
  });

  it("refuses what is not a data: URL", () => {
    expect(() => dataUrlToBlob("https://example.invalid/x.png")).toThrow(/not a data: URL/);
  });
});

describe("the exporter", () => {
  it("never hands a data: URL to fetch", () => {
    const code = readFileSync(join(HERE, "exporters.ts"), "utf8")
      .replace(/\/\*[\s\S]*?\*\//g, "")
      .replace(/\/\/.*$/gm, "");
    expect(code).not.toMatch(/fetch\(\s*(dataUrl|[`"']data:)/);
    expect(code.match(/dataUrlToBlob\(dataUrl\)/g)).toHaveLength(2);
  });
});
