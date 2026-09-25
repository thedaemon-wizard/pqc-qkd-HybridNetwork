/**
 * Every captured frame is in the GIF.
 *
 * modern-gif's convenience `encode({frames})` does not await its frames: a
 * frame given as a URL is queued only after its image loads, and `flush()`
 * had already run. Every GIF this project exported had zero frames (801
 * bytes on the live demo, 2026-09-25). `encodeGifFrames` awaits each frame;
 * this checks that against an encoder whose `encode` resolves late, the way
 * an image load does.
 */
import { describe, expect, it } from "vitest";

import { encodeGifFrames, type GifEncoderLike } from "./exporters";

class SlowEncoder implements GifEncoderLike {
  static last: SlowEncoder;
  queued: string[] = [];
  constructor(public opts: { width: number; height: number }) { SlowEncoder.last = this; }
  async encode(frame: { data: string; delay: number }): Promise<void> {
    await new Promise((r) => setTimeout(r, 5));        // an image load
    this.queued.push(frame.data);
  }
  async flush(): Promise<ArrayBuffer> {
    return new Uint8Array(this.queued.length).buffer;  // one byte per queued frame
  }
}

describe("encodeGifFrames", () => {
  it("queues every frame before it flushes", async () => {
    const frames = ["data:image/png;a", "data:image/png;b", "data:image/png;c", "data:image/png;d"];
    const out = await encodeGifFrames(SlowEncoder, 520, 300, frames, [250, 250, 250, 250]);
    expect((out as ArrayBuffer).byteLength).toBe(frames.length);
    expect(SlowEncoder.last.queued).toEqual(frames);
    expect(SlowEncoder.last.opts).toEqual({ width: 520, height: 300 });
  });

  it("refuses frames and delays that do not pair up", async () => {
    await expect(encodeGifFrames(SlowEncoder, 1, 1, ["a", "b"], [1])).rejects.toThrow(/2 frames but 1 delays/);
  });
});
