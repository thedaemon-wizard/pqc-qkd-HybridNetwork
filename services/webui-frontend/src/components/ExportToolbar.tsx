/**
 * Per-page export toolbar (Phase 12-C).
 *
 * Renders only the buttons whose handlers are passed in. Lazy-load of
 * html-to-image / gifshot keeps initial bundle slim.
 */
import { useRef, useState } from "react";
import {
  downloadCSV, downloadGif, downloadJSON, downloadPNG, downloadServiceLog, downloadWebM,
} from "../lib/exporters";
import Button from "./Button";
import SavedExportsPicker from "./SavedExportsPicker";
import { useDemoMode } from "../lib/useConfig";

export interface ExportToolbarProps {
  /** When set, "💾 Logs" downloads /api/logs/download/<logService>. */
  logService?: string;
  /** Capture this element to PNG / Animation. Defaults to "main". */
  pngTargetSelector?: string;
  /** Returns the JSON snapshot to download when "📋 JSON" is pressed. */
  jsonProvider?: () => unknown;
  /** Returns the row array to download when "📊 CSV" is pressed. */
  csvProvider?: () => Record<string, any>[];
  /** Filename stem (default: "export"). */
  name?: string;
}

export default function ExportToolbar(props: ExportToolbarProps) {
  const [busy, setBusy] = useState<string | null>(null);
  const errRef = useRef<string>("");
  const demo = useDemoMode();

  const name = props.name ?? "export";

  const wrap = async (key: string, fn: () => Promise<void> | void) => {
    setBusy(key); errRef.current = "";
    try { await fn(); }
    catch (e) { errRef.current = String(e); console.error("export", key, e); }
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
      {props.logService && (
        <Button variant="ghost" size="sm" disabled={busy !== null}
                title="Download rotating server log"
                onClick={() => wrap("log",
                  () => downloadServiceLog(props.logService!))}>
          💾 Logs
        </Button>
      )}
      <Button variant="ghost" size="sm" disabled={busy !== null}
              title="Save the current page as a PNG image"
              onClick={() => wrap("png", async () => {
                const t = target();
                if (!t) throw new Error("no target");
                await downloadPNG(name, t);
              })}>
        🖼 PNG
      </Button>
      {props.jsonProvider && (
        <Button variant="ghost" size="sm" disabled={busy !== null}
                title="Save current state as JSON"
                onClick={() => wrap("json",
                  () => downloadJSON(name, props.jsonProvider!()))}>
          📋 JSON
        </Button>
      )}
      {props.csvProvider && (
        <Button variant="ghost" size="sm" disabled={busy !== null}
                title="Save tabular data as CSV"
                onClick={() => wrap("csv",
                  () => downloadCSV(name, props.csvProvider!()))}>
          📊 CSV
        </Button>
      )}
      <Button variant="ghost" size="sm" disabled={busy !== null}
              title="High-quality animation — records 4 s as a WebM video (VP9). Press Run first."
              onClick={() => wrap("webm", async () => {
                const t = target();
                if (!t) throw new Error("no target");
                await downloadWebM(name, t);
              })}>
        🎬 WebM (HQ)
      </Button>
      <Button variant="ghost" size="sm" disabled={busy !== null}
              title="Animated GIF (universally compatible, full-resolution). Press Run first."
              onClick={() => wrap("gif", async () => {
                const t = target();
                if (!t) throw new Error("no target");
                await downloadGif(name, t);
              })}>
        🎞 GIF
      </Button>
      {/* Server-side saved-exports list is hidden in public-demo mode — exports
          fall back to direct client-side downloads (no server files). */}
      {!demo && (
        <>
          <span style={{ width: 1, height: 18, background: "#1d2741", margin: "0 4px" }} />
          <SavedExportsPicker />
        </>
      )}
      {busy && <span style={{ fontSize: 11, color: "#9aa9d8" }}>… {busy}</span>}
      {errRef.current && (
        <span style={{ fontSize: 11, color: "#e25555" }}>✗ {errRef.current}</span>
      )}
    </div>
  );
}
