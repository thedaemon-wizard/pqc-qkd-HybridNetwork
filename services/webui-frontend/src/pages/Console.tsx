import { useEffect, useState } from "react";
import { getLogs } from "../api";
import PageHeader from "../components/PageHeader";
import Button from "../components/Button";
import ExportToolbar from "../components/ExportToolbar";

// Both lanes. The IPsec pair was missing while the public host ran only the
// WireGuard profile; the host added `docker-compose.strongswan.yml` on
// 2026-08-23, so `alice-ipsec`/`bob-ipsec` are real containers whose logs
// carry the charon and VICI traffic (`PPK rotated`, `using PPK for PPK_ID`).
// These six are exactly the names `GET /api/logs/{name}` accepts; any other
// name is a 404 from the backend before Docker is asked. A listed container
// that is not running yields an error line in the pane, which is the honest
// outcome.
const NAMES = [
  "alice", "bob", "bb84-kme-a", "bb84-kme-b", "alice-ipsec", "bob-ipsec",
];

/**
 * Remove SGR colour codes before the log reaches the screen or an export.
 *
 * The arnika pin before release 0.2.0 (3a8cc13) wrote ANSI escapes into every
 * line, and `/api/logs/{name}` passes the container's stdout and stderr
 * through verbatim -- the live endpoint returned, literally:
 *
 *   [INFO] \u001b[36mPRIMARY[1]\u001b[0m [OK] HKDF derivation completed
 *
 * This page's entire content is that string, so it rendered `[36mPRIMARY[1][0m`
 * as visible text, and the exported log carried the escapes into a file
 * offered as evidence. Stripping in ONE place would not have been enough: the
 * render and the export read the same state, so both are fixed by cleaning it
 * on arrival.
 *
 * The current pin (f4cf9ba, the head of the still-open arnika PR #51) logs
 * through slog as key=value lines, with the role as an attribute:
 *
 *   time=... level=INFO msg="sending the key_id to the peer" arnika_id=1 role=primary key_id=<uuid> peer=...
 *
 * and colours a record only when stderr is a terminal (logging.go there), so
 * its lines normally carry no escapes and pass through unchanged. They arrive
 * on the container's stderr, not its stdout: that slog handler writes to
 * os.Stderr (logging.go:42 and :63 there), and the route returns both streams. When they do
 * -- a container run with a TTY -- the escape wraps the whole record, and this
 * strips it the same way. Kept for both reasons: a node rolled back to the old
 * pin still writes the old form.
 *
 * Stripping rather than rendering as colour: the codes carry no information the
 * text does not already have -- the old form printed the role (PRIMARY/BACKUP)
 * as plain text, the slog form as `role=` -- and a log offered as a citable
 * artefact is better as plain text.
 */
const ANSI_SGR = /\x1b\[[0-9;]*m/g;

export function stripAnsi(s: string): string {
  return s.replace(ANSI_SGR, "");
}

export default function Console() {
  const [active, setActive] = useState("alice");
  // The text together with the container it came from. A bare string kept the
  // previous container's log on screen after a switch until the first new
  // poll, and an in-flight request for the old container could land after
  // the switch -- either way the pane and the export (named for the NEW
  // container) carried another container's log.
  const [tail, setTail] = useState<{ container: string; log: string } | null>(null);
  const log = tail?.container === active ? tail.log : "";

  useEffect(() => {
    let stop = false;
    setTail(null);
    async function loop() {
      while (!stop) {
        // A hidden tab does not poll: nobody is reading the tail, and this
        // is the page that asks the public demo for the most data.
        if (document.visibilityState !== "hidden") {
          let text: string;
          try {
            const r = await getLogs(active, 400);
            text = stripAnsi(r.log || "");
          } catch (e) {
            text = `Not observed -- GET /api/logs/${active} failed: ${e instanceof Error ? e.message : e}`;
          }
          // Checked after the await, not only at the loop head: the tab may
          // have switched while the request was in flight.
          if (stop) return;
          setTail({ container: active, log: text });
        }
        await new Promise(r => setTimeout(r, 1500));
      }
    }
    loop();
    return () => { stop = true; };
  }, [active]);

  return (
    <div>
      <PageHeader
        title="Container Console"
        subtitle="Live tail of container stdout and stderr (Docker logs)."
      />
      <div style={{ marginBottom: 12 }}>
        {/* logProvider, not logService. This page already holds the exact text
            it is displaying, and the `logService` route could not name it for
            any of the four containers:

              alice / bob      -> fell through to "webui-backend", a different
                                  service entirely;
              bb84-kme-a / -b  -> asked for bb84-kme-a.log, which does not
                                  exist. The KME writes its rotating file under
                                  the NODE name (alice.log, bob.log), so the
                                  container names in NAMES and the log-file
                                  names occupy different namespaces and the
                                  ternary mapped them backwards.

            Verified against the deployed demo: /api/logs/download/bb84-kme-a
            returned "# log file bb84-kme-a.log not found" with HTTP 200. */}
        <ExportToolbar
          name={`console-${active}`}
          logProvider={() => {
            // Refuse rather than hand over an empty file. `ExportToolbar.wrap`
            // surfaces a throw in the toolbar, but an empty string throws
            // nothing -- which is the same silent-empty-output shape as the
            // backend stub this page's export was just fixed for. The window
            // is short (the poll below fills `log` within 1.5 s) but "saved a
            // 0-byte log" and "the service was quiet" must not look alike.
            if (!log) throw new Error("no log yet: the first poll has not returned");
            return log;
          }}
          jsonProvider={() => ({ container: active, log })}
        />
      </div>
      {/* flexWrap: the six container buttons are one row about 330px wide,
          and at a 320px viewport they pushed the page 27px sideways
          (measured 2026-09-26). They wrap onto a second row instead. From
          375px up they fit on one row, so nothing wraps and nothing moves. */}
      <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginBottom: 12 }}>
        {NAMES.map(n => (
          <Button key={n} variant={active === n ? "primary" : "ghost"}
                  size="sm" onClick={() => setActive(n)}>{n}</Button>
        ))}
      </div>
      <pre style={{
        background: "#070b14", border: "1px solid #1d2741", borderRadius: 8,
        padding: 12, color: "#cbd6f5", fontSize: 11, lineHeight: 1.45,
        maxHeight: "calc(100vh - 220px)", overflow: "auto", whiteSpace: "pre",
      }}>{log || "loading…"}</pre>
    </div>
  );
}
