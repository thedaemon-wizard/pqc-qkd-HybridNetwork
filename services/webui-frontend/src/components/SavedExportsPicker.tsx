/**
 * Saved-exports picker (Phase 13).
 *
 * Pops a dropdown that lists every artefact stored in /var/lib/pqcqkd-exports
 * (PNG / JSON / CSV / GIF / WebM / log). Each entry has a Download link that points
 * at the stable backend URL plus a Delete button.
 *
 * The list refreshes on open and after any delete.
 */
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import Button from "./Button";

/**
 * The open list's width bounds when the viewport has room for them: wide
 * enough to keep a name, its size, Download and Delete on one row, and no
 * wider than a long name needs.
 */
const LIST_MIN_WIDTH_PX = 360;
const LIST_MAX_WIDTH_PX = 520;

/**
 * The least gap the open list keeps from either side of the viewport: the
 * collapsed shell's 16px gutter (lib/layout.ts, NARROW_MAIN_PADDING).
 */
export const LIST_VIEWPORT_GUTTER_PX = 16;

/**
 * The open list's padding and border. Its min and max widths bound the
 * content box, so these add to its width on screen.
 */
const LIST_PADDING_PX = 8;
const LIST_BORDER_PX = 1;

/**
 * The widest content box that keeps the whole list, padding and border
 * included, inside the gutters.
 */
const LIST_FIT_WIDTH = `calc(100vw - ${2 * (LIST_VIEWPORT_GUTTER_PX + LIST_PADDING_PX + LIST_BORDER_PX)}px)`;

/**
 * How far to move a box spanning [left, right] sideways so that it lies within
 * [gutter, viewportWidth - gutter]; 0 when it already does. A box wider than
 * that space is aligned to the left gutter, so its start stays readable.
 */
export function shiftIntoViewport(left: number, right: number, viewportWidth: number, gutter: number): number {
  if (left < gutter || right - left > viewportWidth - 2 * gutter) return gutter - left;
  if (right > viewportWidth - gutter) return viewportWidth - gutter - right;
  return 0;
}

interface Entry {
  name: string; size: number; mtime: number; url: string;
}

function fmtSize(b: number): string {
  if (b < 1024) return `${b} B`;
  if (b < 1024 * 1024) return `${(b / 1024).toFixed(1)} KB`;
  return `${(b / (1024 * 1024)).toFixed(2)} MB`;
}

function fmtTime(t: number): string {
  return new Date(t * 1000).toLocaleString();
}

/**
 * The file-type tag shown before each saved artefact's name. Where
 * ExportToolbar has a button for the type (PNG, JSON, CSV, GIF, WebM), the tag
 * is spelled as that button spells it; LOG and TXT have no button of that
 * name. These were pictographs (one film icon for both GIF and WebM, one
 * floppy disk for log and txt), which a screen reader reads by Unicode name
 * and which did not tell the two video formats apart.
 */
export const TYPE_TAGS: Readonly<Record<string, string>> = {
  png: "PNG", gif: "GIF", webm: "WebM", json: "JSON", csv: "CSV", log: "LOG", txt: "TXT",
};

/** An extension this list does not know is shown as FILE, not guessed at. */
export function typeTag(name: string): string {
  const ext = /\.([a-z0-9]+)$/i.exec(name)?.[1]?.toLowerCase();
  return (ext && TYPE_TAGS[ext]) || "FILE";
}

export default function SavedExportsPicker() {
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState<Entry[] | null>(null);
  const [err, setErr] = useState<string>("");
  const boxRef = useRef<HTMLDivElement>(null);
  const listRef = useRef<HTMLDivElement>(null);

  async function refresh() {
    setErr("");
    try {
      const r = await fetch("/api/exports/list");
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const body = await r.json();
      setItems(body.exports as Entry[]);
    } catch (e) {
      setErr(String(e));
      setItems([]);
    }
  }

  useEffect(() => {
    if (open) refresh();
  }, [open]);

  // close on outside click
  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      if (boxRef.current && !boxRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    // Deferred so the click that opened the picker does not close it. The
    // timer is cleared on cleanup: an open-then-close inside one tick used to
    // add the listener AFTER cleanup had run, and it was never removed.
    const t = setTimeout(() => document.addEventListener("click", handler), 0);
    return () => { clearTimeout(t); document.removeEventListener("click", handler); };
  }, [open]);

  // Keep the open list on screen. It hangs right-aligned under its button,
  // and it is wider than the space to the button's left whenever the button
  // sits near the left of the page: measured on 2026-09-26 on /pqc, the list
  // started 109px left of the viewport at 375px and 16px left of it at 768px,
  // where no scrolling reaches. Moved by a transform after layout, so where it
  // already fits (at 1280px on the same page) nothing changes. Re-placed when
  // its contents load and when the window is resized.
  useLayoutEffect(() => {
    const el = listRef.current;
    if (!open || !el) return;
    const place = () => {
      el.style.transform = "";
      const r = el.getBoundingClientRect();
      const dx = shiftIntoViewport(r.left, r.right, document.documentElement.clientWidth,
                                   LIST_VIEWPORT_GUTTER_PX);
      el.style.transform = dx === 0 ? "" : `translateX(${dx}px)`;
    };
    place();
    window.addEventListener("resize", place);
    return () => window.removeEventListener("resize", place);
  }, [open, items, err]);

  async function remove(name: string) {
    try {
      await fetch(`/api/exports/${encodeURIComponent(name)}`, { method: "DELETE" });
      await refresh();
    } catch (e) {
      setErr(String(e));
    }
  }

  return (
    <div ref={boxRef} style={{ position: "relative", display: "inline-block" }}>
      <Button variant="ghost" size="sm"
              title="Browse backend-saved exports"
              onClick={() => setOpen((o) => !o)}>
        Saved exports
      </Button>
      {open && (
        <div ref={listRef} style={{
          position: "absolute", top: "100%", right: 0, zIndex: 50,
          // No wider than the viewport less its gutters, so a 375px phone can
          // show all of it. From a 570px viewport up (520 + 2 x (16 + 8 + 1))
          // both min()s pick the fixed bounds, so the width at 768px and up is
          // unchanged.
          marginTop: 6, maxHeight: 360,
          minWidth: `min(${LIST_MIN_WIDTH_PX}px, ${LIST_FIT_WIDTH})`,
          maxWidth: `min(${LIST_MAX_WIDTH_PX}px, ${LIST_FIT_WIDTH})`,
          background: "#0d1320", border: `${LIST_BORDER_PX}px solid #2a3760`, borderRadius: 8,
          boxShadow: "0 8px 24px rgba(0,0,0,0.5)",
          padding: LIST_PADDING_PX, overflow: "auto",
        }}>
          <div style={{ display: "flex", justifyContent: "space-between",
                         alignItems: "center", marginBottom: 6 }}>
            <span style={{ fontSize: 11, color: "#6b7796" }}>
              Backend artefacts (/var/lib/pqcqkd-exports)
            </span>
            <Button variant="ghost" size="sm" onClick={refresh}>Refresh</Button>
          </div>
          {err && <div style={{ fontSize: 11, color: "#e25555" }}>{err}</div>}
          {items === null && (
            <div style={{ fontSize: 11, color: "#6b7796" }}>loading…</div>
          )}
          {items && items.length === 0 && (
            <div style={{ fontSize: 11, color: "#6b7796" }}>(empty)</div>
          )}
          {items && items.map((it) => (
            <div key={it.name} style={{
              display: "flex", justifyContent: "space-between",
              alignItems: "center", padding: "4px 6px",
              borderTop: "1px solid #1d2741", fontSize: 11,
              color: "#d8e1ff", gap: 8,
            }}>
              <span style={{ flex: 1, minWidth: 0, overflow: "hidden",
                              textOverflow: "ellipsis", whiteSpace: "nowrap",
                              fontFamily: "monospace" }}
                    title={`${it.name}\n${fmtTime(it.mtime)}`}>
                <span style={{ color: "#6b7796" }}>{typeTag(it.name)}</span> {it.name}
              </span>
              <span style={{ color: "#6b7796", fontFamily: "monospace" }}>
                {fmtSize(it.size)}
              </span>
              <a href={it.url} download={it.name}
                 style={{ color: "#5b8def", textDecoration: "none",
                           padding: "2px 8px", border: "1px solid #5b8def",
                           borderRadius: 4 }}
                 title="Download from backend">
                Download
              </a>
              <Button variant="ghost" size="sm" title="Delete from backend"
                      onClick={() => remove(it.name)}>Delete</Button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
