/**
 * An exported GIF must play back at the speed it was recorded at.
 *
 * The capture loop slept `1000 / fps` between frames and then encoded every
 * frame with that same delay. Rendering an SVG to a PNG data URL is not free,
 * so a frame cost `render + interval` of wall clock while claiming `interval`.
 * A 10-second recording played back in noticeably less than 10 seconds -- the
 * animation in the file ran faster than the animation on screen, which for a
 * demo whose whole point is showing protocol timing is a wrong result, not a
 * cosmetic one.
 *
 * `gifFrameDelays` is a pure function precisely so this is testable without a
 * browser: the capture loop itself needs a DOM, the arithmetic does not.
 */
import { describe, expect, it } from "vitest";

import { gifFrameDelays, noteExportFallback, takeExportNotice } from "./exporters";

describe("GIF frame delays", () => {
  it("sum to the real recording length, not the requested one", () => {
    // 4 fps requested (250 ms), but each render took ~150 ms, so frames landed
    // 400 ms apart. Encoding 250 ms would play 10 s of capture back in 6.25 s.
    const captures = [0, 400, 800, 1200, 1600];
    const endedAt = 2000;
    const delays = gifFrameDelays(captures, endedAt);

    expect(delays).toEqual([400, 400, 400, 400, 400]);
    expect(delays.reduce((a, b) => a + b, 0)).toBe(endedAt - captures[0]);
  });

  it("follows an uneven capture rate rather than averaging it away", () => {
    // Render cost varies with what is on screen; a mean would make the fast
    // stretch too slow and the slow stretch too fast.
    const delays = gifFrameDelays([0, 100, 700, 800], 1000);
    expect(delays).toEqual([100, 600, 100, 200]);
  });

  it("clamps to the shortest delay a GIF decoder will honour", () => {
    // Under 2 centiseconds most decoders substitute 100 ms, which would stretch
    // a fast frame tenfold -- the opposite of the bug, but still wrong.
    expect(gifFrameDelays([0, 5, 10], 15)).toEqual([20, 20, 20]);
  });

  it("gives the final frame the time until recording stopped", () => {
    // Not the interval before it: the last frame is displayed until the loop
    // ends, and using the previous gap loses that tail.
    expect(gifFrameDelays([0, 250], 900)).toEqual([250, 650]);
  });

  it("handles a single captured frame", () => {
    expect(gifFrameDelays([0], 1000)).toEqual([1000]);
  });

  it("returns nothing for no frames", () => {
    expect(gifFrameDelays([], 1000)).toEqual([]);
  });
});

describe("the export notice channel", () => {
  it("is empty when nothing went wrong", () => {
    expect(takeExportNotice()).toBe("");
  });

  it("reports the note that was recorded", () => {
    noteExportFallback("downloaded to this device only");
    expect(takeExportNotice()).toBe("downloaded to this device only");
  });

  it("clears on read, so a later export does not inherit it", () => {
    // The toolbar reads once per export. A sticky notice would keep reporting
    // a stale local-only save long after the backend came back -- and the
    // first version of this test could not tell, because it never set one.
    noteExportFallback("stale");
    expect(takeExportNotice()).toBe("stale");
    expect(takeExportNotice()).toBe("");
  });
});
