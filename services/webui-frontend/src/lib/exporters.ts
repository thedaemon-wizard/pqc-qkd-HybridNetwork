/**
 * Frontend export helpers (Phase 12-C).
 *
 * Each helper takes some in-page state and triggers a browser download.
 * The PNG and GIF helpers lazy-load html-to-image / gifshot so a page that
 * doesn't actually use them keeps the initial bundle small.
 */

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

/** Phase 13: upload a blob to the backend so it persists across browser sessions,
 *  then trigger the browser to download the stable URL the backend returned.
 *  If the backend save fails (e.g. webui-backend offline) we fall back to a
 *  pure-client Blob download so the user always gets something. */
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
    console.warn("backend export save failed, falling back to client-only", e);
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

export async function downloadGif(
  name: string,
  target: HTMLElement | SVGSVGElement,
  durationMs: number = 10000,
  intervalMs: number = 250,
): Promise<void> {
  const frames: string[] = [];
  const t0 = performance.now();
  let frameW = 0, frameH = 0;

  while (performance.now() - t0 < durationMs) {
    try {
      let dataUrl: string;
      if (target instanceof SVGSVGElement) {
        const vb = target.viewBox && target.viewBox.baseVal;
        const w = vb && vb.width ? vb.width : (target.getBoundingClientRect().width || 1240);
        const h = vb && vb.height ? vb.height : (target.getBoundingClientRect().height || 620);
        // Full-resolution GIF frames (cap 1280 to bound size); scale 1 since GIF
        // is 256-colour — extra DPI wouldn't help, only inflate the file.
        const gw = Math.min(Math.round(w), 1280);
        const gh = Math.round(gw * (h / w));
        dataUrl = await svgToPngDataUrl(target, gw, gh, "#0a0e17", 1);
        frameW = gw; frameH = gh;
      } else {
        const mod = await import("html-to-image");
        dataUrl = await mod.toPng(target, { backgroundColor: "#0a0e17" });
        frameW = target.clientWidth || 800;
        frameH = target.clientHeight || 600;
      }
      frames.push(dataUrl);
    } catch (e) { console.warn("frame capture failed", e); }
    await new Promise(r => setTimeout(r, intervalMs));
  }

  if (!frames.length) throw new Error("no frames captured");

  const gifshot = (await import("gifshot")).default;
  await new Promise<void>((resolve, reject) => {
    gifshot.createGIF({
      images: frames,
      gifWidth: frameW,
      gifHeight: frameH,
      interval: intervalMs / 1000,
      numFrames: frames.length,
      sampleInterval: 2,   // 1–30, lower = higher colour quality (default 10)
      numWorkers: 2,
    }, (res: any) => {
      if (res.error) { reject(new Error(res.errorMsg)); return; }
      fetch(res.image).then(r => r.blob()).then(async blob => {
        await saveToBackendAndDownload(blob, name, "gif",
                                         `${name}-${timestamp()}.gif`);
        resolve();
      }).catch(reject);
    });
  });
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
  durationMs: number = 10000,
  fps: number = 25,
): Promise<void> {
  const captureStream = (HTMLCanvasElement.prototype as any).captureStream;
  if (typeof MediaRecorder === "undefined" || !captureStream) {
    throw new Error("WebM recording not supported in this browser — use the GIF Animation instead");
  }
  // Source dimensions (SVG viewBox or element box).
  let w = 1240, h = 600;
  if (target instanceof SVGSVGElement) {
    const vb = target.viewBox && target.viewBox.baseVal;
    w = (vb && vb.width) || target.getBoundingClientRect().width || 1240;
    h = (vb && vb.height) || target.getBoundingClientRect().height || 600;
  } else {
    w = target.clientWidth || 1240; h = target.clientHeight || 600;
  }
  const cw = Math.min(Math.round(w * 2), 1920);     // high-DPI canvas, capped 1920
  const ch = Math.round(cw * (h / w));
  const scale = cw / w;
  const canvas = document.createElement("canvas");
  canvas.width = cw; canvas.height = ch;
  const ctx = canvas.getContext("2d");
  if (!ctx) throw new Error("2D context unavailable");
  ctx.imageSmoothingEnabled = true; ctx.imageSmoothingQuality = "high";
  ctx.fillStyle = "#0a0e17"; ctx.fillRect(0, 0, cw, ch);

  const stream = captureStream.call(canvas, fps) as MediaStream;
  const mime = ["video/webm;codecs=vp9", "video/webm;codecs=vp8", "video/webm"]
    .find((m) => MediaRecorder.isTypeSupported(m)) || "video/webm";
  const rec = new MediaRecorder(stream, { mimeType: mime, videoBitsPerSecond: 12_000_000 });
  const chunks: Blob[] = [];
  rec.ondataavailable = (e) => { if (e.data.size > 0) chunks.push(e.data); };
  const stopped = new Promise<void>((res) => { rec.onstop = () => res(); });

  const loadImg = (src: string) => new Promise<HTMLImageElement>((res, rej) => {
    const i = new Image(); i.onload = () => res(i);
    i.onerror = () => rej(new Error("frame image load failed")); i.src = src;
  });

  rec.start(100);
  const t0 = performance.now();
  while (performance.now() - t0 < durationMs) {
    try {
      let dataUrl: string;
      if (target instanceof SVGSVGElement) {
        dataUrl = await svgToPngDataUrl(target, Math.round(w), Math.round(h), "#0a0e17", scale);
      } else {
        const mod = await import("html-to-image");
        dataUrl = await mod.toPng(target, { backgroundColor: "#0a0e17", pixelRatio: 2 });
      }
      const img = await loadImg(dataUrl);
      ctx.drawImage(img, 0, 0, cw, ch);
    } catch (e) { console.warn("webm frame capture failed", e); }
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
  const blob = await r.blob();
  triggerDownload(blob, `${service}-${timestamp()}.log`);
}
