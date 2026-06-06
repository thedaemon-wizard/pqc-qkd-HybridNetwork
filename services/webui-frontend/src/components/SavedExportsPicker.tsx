/**
 * Saved-exports picker (Phase 13).
 *
 * Pops a dropdown that lists every artefact stored in /var/lib/pqcqkd-exports
 * (PNG / JSON / CSV / GIF / log). Each entry has a Download link that points
 * at the stable backend URL plus a 🗑 Delete button.
 *
 * The list refreshes on open and after any delete.
 */
import { useEffect, useRef, useState } from "react";
import Button from "./Button";

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

function iconFor(name: string): string {
  if (/\.png$/i.test(name)) return "🖼";
  if (/\.gif$/i.test(name)) return "🎞";
  if (/\.json$/i.test(name)) return "📋";
  if (/\.csv$/i.test(name)) return "📊";
  if (/\.log$/i.test(name) || /\.txt$/i.test(name)) return "💾";
  return "📄";
}

export default function SavedExportsPicker() {
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState<Entry[] | null>(null);
  const [err, setErr] = useState<string>("");
  const boxRef = useRef<HTMLDivElement>(null);

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
    setTimeout(() => document.addEventListener("click", handler), 0);
    return () => document.removeEventListener("click", handler);
  }, [open]);

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
        📂 Saved
      </Button>
      {open && (
        <div style={{
          position: "absolute", top: "100%", right: 0, zIndex: 50,
          marginTop: 6, minWidth: 360, maxWidth: 520, maxHeight: 360,
          background: "#0d1320", border: "1px solid #2a3760", borderRadius: 8,
          boxShadow: "0 8px 24px rgba(0,0,0,0.5)",
          padding: 8, overflow: "auto",
        }}>
          <div style={{ display: "flex", justifyContent: "space-between",
                         alignItems: "center", marginBottom: 6 }}>
            <span style={{ fontSize: 11, color: "#6b7796" }}>
              Backend artefacts (/var/lib/pqcqkd-exports)
            </span>
            <Button variant="ghost" size="sm" onClick={refresh}>🔄</Button>
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
                {iconFor(it.name)} {it.name}
              </span>
              <span style={{ color: "#6b7796", fontFamily: "monospace" }}>
                {fmtSize(it.size)}
              </span>
              <a href={it.url} download={it.name}
                 style={{ color: "#5b8def", textDecoration: "none",
                           padding: "2px 8px", border: "1px solid #5b8def",
                           borderRadius: 4 }}
                 title="Download from backend">
                ⬇
              </a>
              <Button variant="ghost" size="sm" title="Delete from backend"
                      onClick={() => remove(it.name)}>🗑</Button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
