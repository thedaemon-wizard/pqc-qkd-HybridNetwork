/**
 * An export must reach the visitor before it reaches the server.
 *
 * `saveToBackendAndDownload` used to upload the blob, wait, and then download
 * it from the URL the backend returned. Two costs:
 *
 *   1. The visitor waited on a round trip for a file their browser already
 *      held -- and base64 inflates a multi-MB PNG or WebM by a third.
 *   2. Every export became server load, on a demo whose standing rule is that
 *      the browser computes and the server is not a bandwidth dependency.
 *      Upload-then-download of the browser's own output is the clearest
 *      violation of that, precisely because it reads as storage.
 *
 * Delivering first also DELETES a failure mode rather than reporting one: by
 * the time the POST can fail, the file is already on disk.
 *
 * Asserted on the source, like the other guards in this directory: the
 * property is an ordering between two side effects, and mounting a DOM to
 * observe an <a download> click would test jsdom more than it tests this.
 */
import { describe, expect, it } from "vitest";

import { readFileSync } from "node:fs";
import { join } from "node:path";

const SRC = readFileSync(
  join(new URL(".", import.meta.url).pathname, "exporters.ts"), "utf8");

/** The body of saveToBackendAndDownload, where the ordering lives. */
function fnBody(): string {
  const i = SRC.indexOf("async function saveToBackendAndDownload");
  expect(i, "saveToBackendAndDownload is gone or was renamed")
    .toBeGreaterThan(-1);
  const next = SRC.indexOf("\nexport async function", i);
  return SRC.slice(i, next > i ? next : undefined);
}

describe("the file is delivered before the upload is attempted", () => {
  it("triggerDownload comes before the POST", () => {
    const body = fnBody();
    const dl = body.indexOf("triggerDownload(");
    const post = body.indexOf('"/api/exports/save"');
    expect(dl, "the local delivery is gone").toBeGreaterThan(-1);
    expect(post, "the catalogue save is gone").toBeGreaterThan(-1);
    expect(dl, "the upload still happens first").toBeLessThan(post);
  });

  it("it is delivered once, not once per path", () => {
    // The old shape called triggerDownload only in the catch. Keeping that
    // call AND adding one up front would download the file twice whenever the
    // backend was down.
    expect(fnBody().match(/triggerDownload\(/g) ?? []).toHaveLength(1);
  });

  it("the download does not depend on the backend's response", () => {
    // Reading `body.url` would put the delivery back behind the network.
    const body = fnBody();
    expect(body).not.toMatch(/a\.href\s*=\s*body\.url/);
    expect(body).not.toMatch(/\.download\s*=\s*body\.filename/);
  });
});

describe("what is reported when the catalogue save fails", () => {
  it("says the catalogue missed a copy, not that the download degraded", () => {
    // Scoped to the CALL, not the whole function. The comment above that call
    // quotes the old wording on purpose, and a whole-body search matches the
    // retraction as readily as a relapse -- which is exactly how this
    // assertion failed on correct code the first time it ran.
    const call = fnBody().match(/noteExportFallback\(`[^`]*`\)/)?.[0] ?? "";
    expect(call, "the notice call is gone or was reshaped").not.toBe("");
    expect(call).toMatch(/saved exports did not get a copy/);
    // The old wording implied a lesser outcome that no longer occurs: the file
    // is always delivered locally now, so calling it a fallback would be a
    // claim about a failure that did not happen.
    expect(call).not.toMatch(/downloaded to this device only/);
  });

  it("the failure is still surfaced, not swallowed", () => {
    expect(fnBody()).toMatch(/noteExportFallback\(/);
  });

  it("a 200 whose body will not parse still counts as a failure", () => {
    // `await r.json()` inside the try. Dropping it would let a malformed
    // response report success for a catalogue entry that does not exist.
    expect(fnBody()).toMatch(/await r\.json\(\)/);
  });
});
