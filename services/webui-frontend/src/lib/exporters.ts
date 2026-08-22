/**
 * Frontend export helpers.
 *
 * Each helper takes some in-page state and triggers a browser download.
 * html-to-image and modern-gif are lazy-loaded so pages that never export
 * keep the initial bundle small.
 *
 * Capture settings below are DEFAULTS, not fixed values -- every one is
 * overridable by the caller. The toolbar exposes three of them to the user:
 * capture duration, WebM frame rate and GIF frame rate. It does NOT expose
 * bitrate; this comment used to say it did.
 */

/** Default animation capture length. */
export const DEFAULT_CAPTURE_MS = 10_000;
/** GIF is 256-colour and grows fast; a lower frame rate is the right default. */
export const DEFAULT_GIF_FPS = 4;
/** Smooth playback without an unreasonable file size. */
export const DEFAULT_WEBM_FPS = 25;
/** ~12 Mbit/s keeps text in the diagrams legible after compression. */
export const DEFAULT_WEBM_BITRATE = 12_000_000;

/** Frame-size caps, to bound export size on large diagrams. */
const GIF_MAX_WIDTH = 1280;
const WEBM_MAX_WIDTH = 1920;
/** MediaRecorder timeslice; smaller values yield more, smaller chunks. */
const WEBM_CHUNK_MS = 100;
/** Matches the app background so exports do not render on transparent black. */
const CANVAS_BG = "#0a0e17";
/**
 * GIF stores frame delay in centiseconds, and most decoders treat anything
 * under 2 cs as "unspecified" and substitute 100 ms. Clamping here keeps a
 * fast frame fast instead of letting the decoder stretch it tenfold.
 */
const MIN_GIF_DELAY_MS = 20;

/**
 * Per-frame delays from the times the frames were actually captured.
 *
 * The capture loop used to sleep `1000 / fps` between frames and then encode
 * every frame with that same delay -- but rendering an SVG to a PNG data URL
 * is not free, so each frame cost `render + interval` of wall clock while
 * claiming to have cost `interval`. A 10-second recording played back in
 * appreciably less than 10 seconds, faster than the animation it recorded.
 *
 * Timing the captures instead makes playback match the recording whatever the
 * render cost, which also means a slow machine produces a shorter but
 * real-time GIF rather than a sped-up one.
 */
export function gifFrameDelays(captureTimes: number[], endedAt: number): number[] {
  return captureTimes.map((t, i) => {
    const until = i + 1 < captureTimes.length ? captureTimes[i + 1] : endedAt;
    return Math.max(MIN_GIF_DELAY_MS, Math.round(until - t));
  });
}

function timestamp(): string {
  const d = new Date();
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}${pad(d.getMonth() + 1)}${pad(d.getDate())}-${pad(d.getHours())}${pad(d.getMinutes())}${pad(d.getSeconds())}`;
}

function triggerDownload(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url; a.download = filename; a.style.display = "none";
  document.body.appendChild(a); a.click();
  setTimeout(() => { document.body.removeChild(a); URL.revokeObjectURL(url); }, 1000);
}

/**
 * A note about the last export, for the toolbar to display.
 *
 * Not an error channel: the user always receives their file. It exists because
 * the backend save can fail while the download succeeds, and the two outcomes
 * are meaningfully different -- one puts the artefact in the saved-exports
 * gallery, the other does not. Previously that difference was a console.warn,
 * so on a static-only deployment every export took the local path, the gallery
 * stayed permanently empty, and nothing on screen explained why.
 */
let pendingNotice = "";

/** Record that the file was delivered, but not everywhere it was meant to go. */
export function noteExportFallback(reason: string): void {
  pendingNotice = reason;
}

/**
 * Read and clear the note left by the most recent export.
 *
 * Clearing on read is the point: the toolbar reads once per export, and a
 * sticky notice would keep reporting a stale local-only save long after the
 * backend came back.
 */
export function takeExportNotice(): string {
  const n = pendingNotice;
  pendingNotice = "";
  return n;
}

/** Upload a blob to the backend so it persists across browser sessions, then
 *  download it from the stable URL the backend returned. When the backend is
 *  absent the file is still delivered from memory, and the difference is
 *  reported through `takeExportNotice` rather than swallowed. */
async function saveToBackendAndDownload(
  blob: Blob, name: string, ext: string, filenameFallback: string,
): Promise<void> {
  try {
    const buf = await blob.arrayBuffer();
    // Chunked base64 — spreading a multi-MB byte array into String.fromCharCode
    // overflows the call stack (high-DPI PNG / WebM are large).
    const bytes = new Uint8Array(buf);
    let binary = "";
    const CHUNK = 0x8000;
    for (let i = 0; i < bytes.length; i += CHUNK) {
      binary += String.fromCharCode.apply(null, bytes.subarray(i, i + CHUNK) as unknown as number[]);
    }
    const b64 = btoa(binary);
    const r = await fetch("/api/exports/save", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, ext, content_b64: b64 }),
    });
    if (!r.ok) throw new Error(`backend save HTTP ${r.status}`);
    const body = await r.json();
    // Trigger a navigation-style download via the stable backend URL
    const a = document.createElement("a");
    a.href = body.url;
    a.download = body.filename;
    a.style.display = "none";
    document.body.appendChild(a); a.click();
    setTimeout(() => document.body.removeChild(a), 500);
  } catch (e) {
    const why = e instanceof Error ? e.message : String(e);
    noteExportFallback(`downloaded to this device only -- not added to saved exports (${why})`);
    console.warn("backend export save failed, delivering the file locally", e);
    triggerDownload(blob, filenameFallback);
  }
}

export async function downloadJSON(name: string, data: unknown): Promise<void> {
  const blob = new Blob(
    [JSON.stringify(data, null, 2)],
    { type: "application/json" },
  );
  await saveToBackendAndDownload(blob, name, "json", `${name}-${timestamp()}.json`);
}

export async function downloadCSV(name: string, rows: Record<string, any>[]): Promise<void> {
  if (!rows.length) {
    await saveToBackendAndDownload(new Blob(["# empty\n"], { type: "text/csv" }),
                                     name, "csv", `${name}-${timestamp()}.csv`);
    return;
  }
  const cols = Array.from(
    rows.reduce((acc: Set<string>, r) => { Object.keys(r).forEach(k => acc.add(k)); return acc; },
                new Set<string>()),
  );
  const esc = (v: any) => {
    if (v == null) return "";
    const s = String(v).replace(/"/g, '""');
    return /[",\n]/.test(s) ? `"${s}"` : s;
  };
  const csv = [
    cols.join(","),
    ...rows.map(r => cols.map(c => esc(r[c])).join(",")),
  ].join("\n");
  await saveToBackendAndDownload(new Blob([csv], { type: "text/csv" }),
                                   name, "csv", `${name}-${timestamp()}.csv`);
}

/**
 * Convert an inline <svg> to a PNG data URL via XMLSerializer + Canvas.
 * This is the standard, reliable path for SVG-only export (html-to-image
 * produced black images because the off-screen cloned SVG never received
 * computed styles or layout). We capture the SVG's intrinsic viewBox so the
 * exported image preserves the *whole* architecture diagram regardless of
 * the on-screen scaled width.
 */
async function svgToPngDataUrl(svg: SVGSVGElement,
                                width: number, height: number,
                                bg: string = "#0a0e17",
                                scale: number = 2): Promise<string> {
  // Clone the SVG so we can inject the xmlns and a fixed size without
  // touching the live DOM, and embed computed styles.
  const clone = svg.cloneNode(true) as SVGSVGElement;
  clone.setAttribute("xmlns", "http://www.w3.org/2000/svg");
  clone.setAttribute("xmlns:xlink", "http://www.w3.org/1999/xlink");
  clone.setAttribute("width", String(width));
  clone.setAttribute("height", String(height));
  // Ensure all text inherits a readable default colour even outside the page.
  const styleEl = document.createElementNS("http://www.w3.org/2000/svg", "style");
  styleEl.textContent =
    "text{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','Hiragino Sans',sans-serif;}";
  clone.insertBefore(styleEl, clone.firstChild);
  const xml = new XMLSerializer().serializeToString(clone);
  const svgBlob = new Blob([
    '<?xml version="1.0" encoding="UTF-8"?>\n', xml,
  ], { type: "image/svg+xml;charset=utf-8" });
  const url = URL.createObjectURL(svgBlob);
  try {
    const img = new Image();
    img.crossOrigin = "anonymous";
    await new Promise<void>((resolve, reject) => {
      img.onload = () => resolve();
      img.onerror = () => reject(new Error("SVG image load failed"));
      img.src = url;
    });
    // Render at `scale`× the intrinsic size for a crisp high-DPI PNG.
    const canvas = document.createElement("canvas");
    canvas.width = Math.round(width * scale);
    canvas.height = Math.round(height * scale);
    const ctx = canvas.getContext("2d");
    if (!ctx) throw new Error("2D context unavailable");
    ctx.imageSmoothingEnabled = true;
    ctx.imageSmoothingQuality = "high";
    ctx.fillStyle = bg;
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
    return canvas.toDataURL("image/png");
  } finally {
    URL.revokeObjectURL(url);
  }
}

export async function downloadPNG(name: string,
                                   target: HTMLElement | SVGSVGElement): Promise<void> {
  if (target instanceof SVGSVGElement) {
    // Prefer the explicit viewBox dimensions so the exported PNG matches the
    // architecture diagram's full canvas, not the squashed on-screen size.
    const vb = target.viewBox && target.viewBox.baseVal;
    const w = vb && vb.width ? vb.width : (target.getBoundingClientRect().width || 1240);
    const h = vb && vb.height ? vb.height : (target.getBoundingClientRect().height || 620);
    const dataUrl = await svgToPngDataUrl(target, Math.round(w), Math.round(h));
    const blob = await (await fetch(dataUrl)).blob();
    await saveToBackendAndDownload(blob, name, "png", `${name}-${timestamp()}.png`);
    return;
  }
  const mod = await import("html-to-image");
  // pixelRatio 2 → high-DPI/retina-quality PNG (default ~1 was low quality).
  const dataUrl = await mod.toPng(target, { backgroundColor: "#0a0e17", pixelRatio: 2 });
  const blob = await (await fetch(dataUrl)).blob();
  await saveToBackendAndDownload(blob, name, "png", `${name}-${timestamp()}.png`);
}

/**
 * Animated GIF export.
 *
 * Encoded with `modern-gif`, which is actively maintained and does its
 * quantisation in a worker. It replaced `gifshot`, which had not been released
 * since 2017, shipped no type declarations, and was the only remaining
 * unmaintained runtime dependency.
 *
 * GIF is capped at 256 colours, so frames are captured at scale 1 -- extra DPI
 * cannot survive quantisation and would only inflate the file. Use WebM for a
 * high-fidelity capture.
 */
export async function downloadGif(
  name: string,
  target: HTMLElement | SVGSVGElement,
  durationMs: number = DEFAULT_CAPTURE_MS,
  fps: number = DEFAULT_GIF_FPS,
): Promise<void> {
  if (fps <= 0) throw new Error(`gif fps must be positive, got ${fps}`);
  const intervalMs = 1000 / fps;

  const frames: string[] = [];
  const captureTimes: number[] = [];
  const t0 = performance.now();
  // Absolute schedule rather than a fixed sleep, so a slow render steals from
  // the next gap instead of adding to the total.
  let nextCaptureAt = t0;
  let frameW = 0, frameH = 0;

  while (performance.now() - t0 < durationMs) {
    captureTimes.push(performance.now());
    let dataUrl: string;
    if (target instanceof SVGSVGElement) {
      const vb = target.viewBox && target.viewBox.baseVal;
      const w = vb && vb.width ? vb.width : (target.getBoundingClientRect().width || 1240);
      const h = vb && vb.height ? vb.height : (target.getBoundingClientRect().height || 620);
      const gw = Math.min(Math.round(w), GIF_MAX_WIDTH);
      const gh = Math.round(gw * (h / w));
      dataUrl = await svgToPngDataUrl(target, gw, gh, CANVAS_BG, 1);
      frameW = gw; frameH = gh;
    } else {
      const mod = await import("html-to-image");
      dataUrl = await mod.toPng(target, { backgroundColor: CANVAS_BG });
      frameW = target.clientWidth;
      frameH = target.clientHeight;
    }
    frames.push(dataUrl);
    nextCaptureAt += intervalMs;
    const wait = nextCaptureAt - performance.now();
    if (wait > 0) await new Promise(r => setTimeout(r, wait));
  }
  const endedAt = performance.now();

  if (!frames.length) throw new Error("no frames captured");
  if (!frameW || !frameH) throw new Error("target has zero size; nothing to record");

  const { encode } = await import("modern-gif");
  const delays = gifFrameDelays(captureTimes, endedAt);
  const output = await encode({
    width: frameW,
    height: frameH,
    frames: frames.map((src, i) => ({ data: src, delay: delays[i] })),
  });

  await saveToBackendAndDownload(
    new Blob([output as BlobPart], { type: "image/gif" }),
    name, "gif", `${name}-${timestamp()}.gif`,
  );
}

/**
 * High-quality animation export as WebM (2026 best practice — no 256-colour GIF
 * limit). Records the live diagram via MediaRecorder + canvas.captureStream:
 * each frame the current SVG is rendered to a high-DPI canvas being streamed,
 * and VP9/VP8 chunks are muxed into a .webm. The animation must be running
 * (press Run first) for a meaningful capture.
 */
export async function downloadWebM(
  name: string,
  target: HTMLElement | SVGSVGElement,
  durationMs: number = DEFAULT_CAPTURE_MS,
  fps: number = DEFAULT_WEBM_FPS,
  bitsPerSecond: number = DEFAULT_WEBM_BITRATE,
): Promise<void> {
  const captureStream = (HTMLCanvasElement.prototype as any).captureStream;
  if (typeof MediaRecorder === "undefined" || !captureStream) {
    throw new Error("WebM recording not supported in this browser — use the GIF Animation instead");
  }
  if (fps <= 0) throw new Error(`webm fps must be positive, got ${fps}`);

  // Source dimensions: the SVG viewBox, or the element's own box.
  let w: number, h: number;
  if (target instanceof SVGSVGElement) {
    const vb = target.viewBox && target.viewBox.baseVal;
    const box = target.getBoundingClientRect();
    w = (vb && vb.width) || box.width;
    h = (vb && vb.height) || box.height;
  } else {
    w = target.clientWidth; h = target.clientHeight;
  }
  if (!w || !h) throw new Error("target has zero size; nothing to record");

  const cw = Math.min(Math.round(w * 2), WEBM_MAX_WIDTH);  // high-DPI, capped
  const ch = Math.round(cw * (h / w));
  const scale = cw / w;
  const canvas = document.createElement("canvas");
  canvas.width = cw; canvas.height = ch;
  const ctx = canvas.getContext("2d");
  if (!ctx) throw new Error("2D context unavailable");
  ctx.imageSmoothingEnabled = true; ctx.imageSmoothingQuality = "high";
  ctx.fillStyle = CANVAS_BG; ctx.fillRect(0, 0, cw, ch);

  const stream = captureStream.call(canvas, fps) as MediaStream;
  // Codec support genuinely varies by browser and platform, so negotiate at
  // runtime rather than assuming VP9.
  const mime = ["video/webm;codecs=vp9", "video/webm;codecs=vp8", "video/webm"]
    .find((m) => MediaRecorder.isTypeSupported(m)) || "video/webm";
  const rec = new MediaRecorder(stream, { mimeType: mime, videoBitsPerSecond: bitsPerSecond });
  const chunks: Blob[] = [];
  rec.ondataavailable = (e) => { if (e.data.size > 0) chunks.push(e.data); };
  const stopped = new Promise<void>((res) => { rec.onstop = () => res(); });

  const loadImg = (src: string) => new Promise<HTMLImageElement>((res, rej) => {
    const i = new Image(); i.onload = () => res(i);
    i.onerror = () => rej(new Error("frame image load failed")); i.src = src;
  });

  rec.start(WEBM_CHUNK_MS);
  const t0 = performance.now();
  while (performance.now() - t0 < durationMs) {
    let dataUrl: string;
    if (target instanceof SVGSVGElement) {
      dataUrl = await svgToPngDataUrl(target, Math.round(w), Math.round(h), CANVAS_BG, scale);
    } else {
      const mod = await import("html-to-image");
      dataUrl = await mod.toPng(target, { backgroundColor: CANVAS_BG, pixelRatio: 2 });
    }
    const img = await loadImg(dataUrl);
    ctx.drawImage(img, 0, 0, cw, ch);
    await new Promise((r) => setTimeout(r, 1000 / fps));
  }
  rec.stop();
  await stopped;
  const blob = new Blob(chunks, { type: "video/webm" });
  if (!blob.size) throw new Error("WebM capture produced no data");
  await saveToBackendAndDownload(blob, name, "webm", `${name}-${timestamp()}.webm`);
}

export async function downloadServiceLog(service: string, lines: number = 1000): Promise<void> {
  const r = await fetch(`/api/logs/download/${service}?lines=${lines}`);
  // Check the status. Without this, a 404 or 500 body downloaded as a .log and
  // looked like a successful export of an empty-looking file.
  if (!r.ok) {
    throw new Error(`server log ${service} unavailable (HTTP ${r.status})`);
  }
  const text = await r.text();
  // The backend answers 200 with this literal when the file is absent, so a
  // status check alone is not enough to tell "no log" from "here is the log".
  if (text.startsWith("# log file") && text.includes("not found")) {
    throw new Error(`server has no log for ${service} yet`);
  }
  triggerDownload(new Blob([text], { type: "text/plain" }),
                  `${service}-${timestamp()}.log`);
}

/**
 * Save client-side text (a run log) without a server round trip.
 *
 * Deliberately does NOT go through saveToBackendAndDownload: a page that
 * computes entirely in the browser should not have to post its log to the
 * backend to hand it to the user.
 */
export function downloadText(name: string, ext: string, text: string): void {
  triggerDownload(new Blob([text], { type: "text/plain" }),
                  `${name}-${timestamp()}.${ext}`);
}
