/**
 * Per-page export toolbar (Phase 12-C).
 *
 * Renders only the buttons whose handlers are passed in. Lazy-load of
 * html-to-image / modern-gif keeps initial bundle slim. (This credited
 * gifshot, which was replaced -- it was last released in 2017.)
 *
 * Labels are words, not pictographs: each button was prefixed with an emoji
 * (a floppy disk for Logs, a framed picture for PNG, and so on), and the three
 * capture selects were labelled by a stopwatch and two film icons alone. An
 * emoji's glyph depends on the font the visitor has, and a screen reader reads
 * it by its Unicode name ("floppy disk"), which is not what the control does.
 * SavedExportsPicker uses the same file-type words.
 */
import { useState } from "react";
import {
  DEFAULT_CAPTURE_MS, DEFAULT_GIF_FPS, DEFAULT_WEBM_BITRATE, DEFAULT_WEBM_FPS,
  downloadCSV, downloadGif, downloadJSON, downloadPNG, downloadServiceLog, downloadText,
  downloadWebM, takeExportNotice,
} from "../lib/exporters";
import Button from "./Button";
import SavedExportsPicker from "./SavedExportsPicker";

/**
 * The choices offered by the Length, WebM and GIF selects. Each list contains
 * its default (DEFAULT_CAPTURE_MS in seconds, DEFAULT_WEBM_FPS,
 * DEFAULT_GIF_FPS): a controlled select whose value is not among its options
 * displays the first option while capturing with the default, so the control
 * would misreport what a capture uses. exportToolbarDefaults.test.ts checks
 * both the lists and that membership.
 */
export const CAPTURE_LENGTH_OPTIONS_SEC: readonly number[] = [3, 5, 10, 15, 20, 30, 60];
export const WEBM_FPS_OPTIONS: readonly number[] = [12, 15, 24, 25, 30, 60];
export const GIF_FPS_OPTIONS: readonly number[] = [2, 4, 8, 10, 15];

export interface ExportToolbarProps {
  /** When set, "Logs" downloads /api/logs/download/<logService>. */
  logService?: string;
  /**
   * Returns the CLIENT-side run log to save when "Logs" is pressed.
   *
   * Takes precedence over `logService`. On a page whose simulation runs
   * entirely in the browser, the server log contains nothing about the run, so
   * offering it under a "Logs" button is actively misleading -- the user gets a
   * successful download of an unrelated file.
   */
  logProvider?: () => string;
  /** Capture this element to PNG / Animation. Defaults to "main". */
  pngTargetSelector?: string;
  /** Returns the JSON snapshot to download when "JSON" is pressed. */
  jsonProvider?: () => unknown;
  /** Returns the row array to download when "CSV" is pressed. */
  csvProvider?: () => Record<string, any>[];
  /** Filename stem (default: "export"). */
  name?: string;
  /**
   * Whether this page has a Run control that must be started before an
   * animation capture shows anything.
   *
   * The WebM and GIF tooltips ended with "Press Run first." unconditionally.
   * Thirteen pages mount this toolbar and only three -- `/e2e`, `/paper-flow`
   * and `/protocol-lab` -- have a Run button, so on the other ten the hint
   * would tell the reader to press a control that does not exist. Pages such as
   * `/bb84` animate continuously and need no start.
   *
   * Default false, so a page opts in rather than inheriting an instruction
   * that happens to be wrong for it.
   */
  hasRunControl?: boolean;
  /**
   * Whether the page changes over time, so a WebM or GIF capture shows
   * something a PNG does not. Default true. Pages whose content is a finished
   * result table (`/pqc`, `/verify`), a status page that changes only on its
   * poll (`/vpn`) or a static figure (`/`, `/topology`, `/keyflow`) pass
   * false, and the WebM and GIF buttons and their three selects are not
   * rendered: ten seconds of video of a table that does not move is an
   * artefact with nothing in it.
   */
  animated?: boolean;
}

export default function ExportToolbar(props: ExportToolbarProps) {
  const [busy, setBusy] = useState<string | null>(null);
  // State, not a ref: writing to a ref does not schedule a render, so export
  // failures were only ever shown if some unrelated state change happened to
  // repaint the toolbar. In practice they were invisible.
  const [error, setError] = useState<string>("");
  // Distinct from `error`: the export succeeded, but not everywhere the user
  // might expect it to have gone.
  const [notice, setNotice] = useState<string>("");
  // Empty on pages with no Run button. See `hasRunControl`.
  const runHint = props.hasRunControl ? " Press Run first." : "";
  const animated = props.animated ?? true;
  // User-selectable animation capture settings (WebM/GIF).
  const [durationSec, setDurationSec] = useState(DEFAULT_CAPTURE_MS / 1000);
  const [gifFps, setGifFps] = useState(DEFAULT_GIF_FPS);
  const [webmFps, setWebmFps] = useState(DEFAULT_WEBM_FPS);
  // Off by default: a download stays on this device unless the user asks for
  // a copy in the shared gallery (exporters.ts, ExportOptions.gallery).
  const [gallery, setGallery] = useState(false);
  const opts = { gallery };

  const name = props.name ?? "export";

  const wrap = async (key: string, fn: () => Promise<void> | void) => {
    setBusy(key); setError(""); setNotice("");
    try { await fn(); setNotice(takeExportNotice()); }
    catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      console.error("export", key, e);
    }
    finally { setBusy(null); }
  };

  const target = () => {
    const sel = props.pngTargetSelector ?? "main";
    const el = document.querySelector(sel);
    return el as HTMLElement | SVGSVGElement | null;
  };

  return (
    <div style={{
      display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap",
      padding: "8px 12px",
      background: "#0d1320",
      border: "1px solid #1d2741",
      borderRadius: 8,
    }}>
      <span style={{ fontSize: 11, color: "#6b7796", marginRight: 4 }}>
        Save artefact:
      </span>
      {(props.logProvider || props.logService) && (
        <Button variant="ghost" size="sm" disabled={busy !== null}
                title={props.logProvider
                  ? "Download this run's log (client-side)"
                  : "Download rotating server log"}
                onClick={() => wrap("log", () => props.logProvider
                  ? downloadText(`${name}-log`, "log", props.logProvider())
                  : downloadServiceLog(props.logService!))}>
          Logs
        </Button>
      )}
      <Button variant="ghost" size="sm" disabled={busy !== null}
              title="Save the current page as a PNG image"
              onClick={() => wrap("png", async () => {
                const t = target();
                if (!t) throw new Error("no target");
                await downloadPNG(name, t, opts);
              })}>
        PNG
      </Button>
      {props.jsonProvider && (
        <Button variant="ghost" size="sm" disabled={busy !== null}
                title="Save current state as JSON"
                onClick={() => wrap("json",
                  () => downloadJSON(name, props.jsonProvider!(), opts))}>
          JSON
        </Button>
      )}
      {props.csvProvider && (
        <Button variant="ghost" size="sm" disabled={busy !== null}
                title="Save tabular data as CSV"
                onClick={() => wrap("csv",
                  () => downloadCSV(name, props.csvProvider!(), opts))}>
          CSV
        </Button>
      )}
      {animated && (<>
      <Button variant="ghost" size="sm" disabled={busy !== null}
              title={`High-quality animation — records ${durationSec}s as a WebM video (VP9).${runHint}`}
              onClick={() => wrap("webm", async () => {
                const t = target();
                if (!t) throw new Error("no target");
                await downloadWebM(name, t, durationSec * 1000, webmFps, DEFAULT_WEBM_BITRATE, opts);
              })}>
        WebM (HQ)
      </Button>
      <Button variant="ghost" size="sm" disabled={busy !== null}
              title={`Animated GIF (universally compatible, full-resolution), ${durationSec}s.${runHint}`}
              onClick={() => wrap("gif", async () => {
                const t = target();
                if (!t) throw new Error("no target");
                await downloadGif(name, t, durationSec * 1000, gifFps, opts);
              })}>
        GIF
      </Button>
      {/* Animation capture duration selector (WebM / GIF) — default 10 s. */}
      <label title="Animation capture duration (WebM / GIF)"
             style={{ fontSize: 11, color: "#9aa9d8", display: "inline-flex",
                       alignItems: "center", gap: 4 }}>
        Length
        <select value={durationSec} disabled={busy !== null}
                onChange={(e) => setDurationSec(parseInt(e.target.value, 10))}
                aria-label="Animation duration (seconds)"
                style={{ background: "#0d1320", color: "#cbd6f5",
                          border: "1px solid #2a3760", borderRadius: 4,
                          padding: "2px 4px", fontSize: 11,
                          cursor: busy !== null ? "not-allowed" : "pointer" }}>
          {CAPTURE_LENGTH_OPTIONS_SEC.map((s) => (
            <option key={s} value={s}>{s}s</option>
          ))}
        </select>
      </label>
      {/* Frame rates. Exposed rather than hardcoded: GIF is 256-colour and
          grows fast, so it wants a low rate, while WebM can afford a smooth
          one. The right trade-off depends on what is being recorded. */}
      <label title="WebM frame rate"
             style={{ fontSize: 11, color: "#9aa9d8", display: "inline-flex",
                       alignItems: "center", gap: 4 }}>
        WebM at
        <select value={webmFps} disabled={busy !== null}
                onChange={(e) => setWebmFps(parseInt(e.target.value, 10))}
                aria-label="WebM frame rate (fps)"
                style={selStyle(busy !== null)}>
          {WEBM_FPS_OPTIONS.map((f) => (
            <option key={f} value={f}>{f} fps</option>
          ))}
        </select>
      </label>
      <label title="GIF frame rate"
             style={{ fontSize: 11, color: "#9aa9d8", display: "inline-flex",
                       alignItems: "center", gap: 4 }}>
        GIF at
        <select value={gifFps} disabled={busy !== null}
                onChange={(e) => setGifFps(parseInt(e.target.value, 10))}
                aria-label="GIF frame rate (fps)"
                style={selStyle(busy !== null)}>
          {GIF_FPS_OPTIONS.map((f) => (
            <option key={f} value={f}>{f} fps</option>
          ))}
        </select>
      </label>
      </>)}
      {/* Server-side saved-exports gallery. Reading it is always available;
          adding to it is an explicit choice per toolbar, not a side effect of
          every download. */}
      <span style={{ width: 1, height: 18, background: "#1d2741", margin: "0 4px" }} />
      <label title="Also upload a copy of each export to the shared saved-exports gallery, which every visitor can see. Off: the file only downloads to this device."
             style={{ fontSize: 11, color: "#9aa9d8", display: "inline-flex",
                       alignItems: "center", gap: 4 }}>
        <input type="checkbox" checked={gallery} disabled={busy !== null}
               aria-label="Also save a copy to the shared gallery"
               onChange={(e) => setGallery(e.target.checked)} />
        copy to shared gallery
      </label>
      <SavedExportsPicker />
      {busy && <span style={{ fontSize: 11, color: "#9aa9d8" }}>… {busy}</span>}
      {error && (
        <span style={{ fontSize: 11, color: "#e25555" }} role="alert">export failed: {error}</span>
      )}
      {!error && notice && (
        <span style={{ fontSize: 11, color: "#e0a33a" }} role="status">{notice}</span>
      )}
    </div>
  );
}

const selStyle = (disabled: boolean): React.CSSProperties => ({
  background: "#0d1320", color: "#cbd6f5", border: "1px solid #2a3760",
  borderRadius: 4, padding: "2px 4px", fontSize: 11,
  cursor: disabled ? "not-allowed" : "pointer",
});
