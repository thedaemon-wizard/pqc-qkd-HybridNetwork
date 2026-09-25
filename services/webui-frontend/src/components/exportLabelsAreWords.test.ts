/**
 * The export toolbar and the saved-exports picker label their controls with
 * words. They used emoji -- a floppy disk for Logs, one film icon for both GIF
 * and WebM -- whose glyph depends on the visitor's fonts and which a screen
 * reader announces by Unicode name rather than by what the control does.
 */
import { describe, expect, it } from "vitest";

import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { TYPE_TAGS, typeTag } from "./SavedExportsPicker";

const HERE = dirname(fileURLToPath(import.meta.url));
const FILES = ["ExportToolbar.tsx", "SavedExportsPicker.tsx"];
/** Any character Unicode marks as pictographic, which covers every emoji used before. */
const PICTOGRAPH = /\p{Extended_Pictographic}/u;

describe("no pictographs", () => {
  it.each(FILES)("%s contains none, in labels or comments", (f) => {
    const src = readFileSync(join(HERE, f), "utf8");
    const hit = src.split("\n").findIndex((line) => PICTOGRAPH.test(line));
    expect(hit, `${f}:${hit + 1}`).toBe(-1);
  });
});

describe("the saved-exports list tags each file by type", () => {
  it.each([
    ["bb84-20260926.png", "PNG"], ["e2e.gif", "GIF"], ["paper-flow.webm", "WebM"],
    ["pqc.json", "JSON"], ["bb84.csv", "CSV"], ["bb84-log.log", "LOG"], ["notes.TXT", "TXT"],
  ])("%s -> %s", (name, tag) => {
    expect(typeTag(name)).toBe(tag);
  });

  it("tells GIF and WebM apart, which the shared film icon did not", () => {
    expect(typeTag("a.gif")).not.toBe(typeTag("a.webm"));
  });

  it("does not guess at an extension it does not know", () => {
    expect(typeTag("archive.tar.zst")).toBe("FILE");
    expect(typeTag("no-extension")).toBe("FILE");
  });
});

describe("the toolbar's buttons use the same words", () => {
  const src = readFileSync(join(HERE, "ExportToolbar.tsx"), "utf8");
  const BUTTONS = ["Logs", "PNG", "JSON", "CSV", "WebM (HQ)", "GIF"];
  it.each(BUTTONS)("has a %s button", (label) => {
    const escaped = label.replace(/[()]/g, "\\$&");
    expect(src).toMatch(new RegExp(`>\\s*${escaped}\\s*</Button>`));
  });

  it.each(["png", "json", "csv", "gif", "webm"])(
    "tags .%s with the word its toolbar button starts with", (ext) => {
      // TYPE_TAGS' comment promises this spelling; this holds it to it.
      const tag = TYPE_TAGS[ext];
      expect(BUTTONS.some((b) => b === tag || b.startsWith(`${tag} `)), tag).toBe(true);
    });
});
