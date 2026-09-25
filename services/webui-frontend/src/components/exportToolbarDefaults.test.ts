/**
 * What the export toolbar does before anyone touches it.
 *
 * A reader who opens a page and presses WebM or GIF gets the defaults, so the
 * defaults are the capture: a ten-second recording, handed to the encoder in
 * the unit the encoder reads, and kept on this device unless the reader ticks
 * the shared-gallery box. Pages whose content does not move pass
 * `animated={false}` and get no animation controls at all.
 *
 * The toolbar is rendered to static markup with its Button swapped for one
 * that records its props, so the WebM and GIF click handlers can be invoked
 * directly and the arguments they pass to the (mocked) encoders read back.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { createElement, type ReactNode } from "react";
import { renderToStaticMarkup } from "react-dom/server";

import type { ButtonProps } from "./Button";

const pressed = vi.hoisted(() => ({ buttons: [] as ButtonProps[] }));

vi.mock("./Button", () => ({
  default: (props: ButtonProps) => {
    pressed.buttons.push(props);
    return createElement("button", { title: props.title }, props.children);
  },
}));

vi.mock("../lib/exporters", async (importOriginal) => {
  const real = await importOriginal<typeof import("../lib/exporters")>();
  return {
    ...real,
    downloadWebM: vi.fn(async () => {}),
    downloadGif: vi.fn(async () => {}),
  };
});

import ExportToolbar, {
  CAPTURE_LENGTH_OPTIONS_SEC, GIF_FPS_OPTIONS, WEBM_FPS_OPTIONS, type ExportToolbarProps,
} from "./ExportToolbar";
import {
  DEFAULT_CAPTURE_MS, DEFAULT_GIF_FPS, DEFAULT_WEBM_BITRATE, DEFAULT_WEBM_FPS,
  downloadGif, downloadWebM,
} from "../lib/exporters";

const HERE = dirname(fileURLToPath(import.meta.url));
const MS_PER_S = 1000;
/** The filename stem passed to the toolbar, so the hand-off can be matched on it. */
const NAME = "defaults-probe";
/** The accessible names the toolbar gives its three animation selects. */
const LENGTH_SELECT = "Animation duration (seconds)";
const WEBM_SELECT = "WebM frame rate (fps)";
const GIF_SELECT = "GIF frame rate (fps)";
const GALLERY_BOX = "Also save a copy to the shared gallery";

function render(props: ExportToolbarProps = {}): string {
  pressed.buttons.length = 0;
  return renderToStaticMarkup(createElement(ExportToolbar, { name: NAME, ...props }));
}

/** The markup of the <select> with this aria-label, through its closing tag. */
function selectMarkup(html: string, ariaLabel: string): string {
  const open = html.indexOf(`aria-label="${ariaLabel}"`);
  expect(open, `no select labelled "${ariaLabel}"`).toBeGreaterThan(-1);
  const start = html.lastIndexOf("<select", open);
  return html.slice(start, html.indexOf("</select>", open));
}

/** The values of a select's options, in document order. */
function optionValues(html: string, ariaLabel: string): number[] {
  return [...selectMarkup(html, ariaLabel).matchAll(/<option value="(\d+)"/g)]
    .map((m) => Number(m[1]));
}

/** The value of the option the server render marked as selected. */
function selectedValue(html: string, ariaLabel: string): number {
  const m = /<option value="(\d+)" selected=""/.exec(selectMarkup(html, ariaLabel));
  expect(m, `no selected option in "${ariaLabel}"`).not.toBeNull();
  return Number(m![1]);
}

function label(children: ReactNode): string {
  return Array.isArray(children) ? children.join("") : String(children);
}

function buttonNamed(text: string): ButtonProps {
  const b = pressed.buttons.find((p) => label(p.children).trim() === text);
  expect(b, `no "${text}" button rendered`).toBeDefined();
  return b!;
}

describe("capture length", () => {
  it("defaults to 10 s", () => {
    expect(DEFAULT_CAPTURE_MS).toBe(10 * MS_PER_S);
    expect(selectedValue(render(), LENGTH_SELECT)).toBe(DEFAULT_CAPTURE_MS / MS_PER_S);
  });

  it("offers exactly the component's list, in order", () => {
    expect(CAPTURE_LENGTH_OPTIONS_SEC).toEqual([3, 5, 10, 15, 20, 30, 60]);
    expect(optionValues(render(), LENGTH_SELECT)).toEqual([...CAPTURE_LENGTH_OPTIONS_SEC]);
  });
});

describe("every select opens on its own default", () => {
  // A controlled select whose value is not one of its options shows the first
  // option instead, while the capture still uses the default.
  it.each([
    [LENGTH_SELECT, CAPTURE_LENGTH_OPTIONS_SEC, DEFAULT_CAPTURE_MS / MS_PER_S],
    [WEBM_SELECT, WEBM_FPS_OPTIONS, DEFAULT_WEBM_FPS],
    [GIF_SELECT, GIF_FPS_OPTIONS, DEFAULT_GIF_FPS],
  ])("%s", (aria, options, dflt) => {
    expect(options).toContain(dflt);
    const html = render();
    expect(optionValues(html, aria)).toEqual([...options]);
    expect(selectedValue(html, aria)).toBe(dflt);
  });
});

describe("the encoders receive the length in milliseconds", () => {
  const target = { tagName: "MAIN" };

  beforeEach(() => {
    vi.mocked(downloadWebM).mockClear();
    vi.mocked(downloadGif).mockClear();
    vi.stubGlobal("document", { querySelector: () => target });
  });
  afterEach(() => { vi.unstubAllGlobals(); });

  it("both encoders take a duration in ms", () => {
    // The unit is fixed by the parameter the toolbar's argument lands in.
    const src = readFileSync(join(HERE, "..", "lib", "exporters.ts"), "utf8");
    for (const fn of ["downloadWebM", "downloadGif"]) {
      const sig = src.slice(src.indexOf(`export async function ${fn}(`));
      expect(sig.slice(0, sig.indexOf(")")), fn)
        .toMatch(/target: [^,]+,\s*durationMs: number = DEFAULT_CAPTURE_MS,/);
    }
  });

  it("WebM gets the default length, its own frame rate and bitrate, and no gallery copy", async () => {
    render();
    await buttonNamed("WebM (HQ)").onClick!();
    expect(downloadWebM).toHaveBeenCalledTimes(1);
    expect(downloadWebM).toHaveBeenCalledWith(
      NAME, target, DEFAULT_CAPTURE_MS, DEFAULT_WEBM_FPS, DEFAULT_WEBM_BITRATE, { gallery: false });
  });

  it("GIF gets the same length and its own frame rate, and no gallery copy", async () => {
    render();
    await buttonNamed("GIF").onClick!();
    expect(downloadGif).toHaveBeenCalledTimes(1);
    expect(downloadGif).toHaveBeenCalledWith(
      NAME, target, DEFAULT_CAPTURE_MS, DEFAULT_GIF_FPS, { gallery: false });
  });

  it("the tooltips state the same length in seconds", () => {
    render();
    const s = DEFAULT_CAPTURE_MS / MS_PER_S;
    expect(buttonNamed("WebM (HQ)").title).toContain(`records ${s}s`);
    expect(buttonNamed("GIF").title).toContain(`${s}s.`);
  });
});

describe("animated={false}", () => {
  it("renders no WebM or GIF button and none of the three selects", () => {
    const html = render({ animated: false });
    const labels = pressed.buttons.map((b) => label(b.children).trim());
    expect(labels).toContain("PNG");
    expect(labels).not.toContain("WebM (HQ)");
    expect(labels).not.toContain("GIF");
    for (const aria of [LENGTH_SELECT, WEBM_SELECT, GIF_SELECT]) {
      expect(html).not.toContain(`aria-label="${aria}"`);
    }
  });

  it("the default is animated", () => {
    render();
    const labels = pressed.buttons.map((b) => label(b.children).trim());
    expect(labels).toContain("WebM (HQ)");
    expect(labels).toContain("GIF");
  });
});

describe("copy to shared gallery", () => {
  it("is present and unticked by default", () => {
    const html = render();
    const at = html.indexOf(`aria-label="${GALLERY_BOX}"`);
    expect(at).toBeGreaterThan(-1);
    const input = html.slice(html.lastIndexOf("<input", at), html.indexOf(">", at) + 1);
    expect(input).toContain('type="checkbox"');
    expect(input).not.toMatch(/\bchecked\b/);
  });
});
