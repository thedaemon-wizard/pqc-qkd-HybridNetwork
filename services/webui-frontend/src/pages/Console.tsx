import { useEffect, useState } from "react";
import { getLogs } from "../api";
import PageHeader from "../components/PageHeader";
import Button from "../components/Button";
import ExportToolbar from "../components/ExportToolbar";

// Both lanes. The IPsec pair was missing while the public host ran only the
// WireGuard profile; the host added `docker-compose.strongswan.yml` on
// 2026-08-23, so `alice-ipsec`/`bob-ipsec` are real containers whose logs
// carry the charon and VICI traffic (`PPK rotated`, `using PPK for PPK_ID`).
// A name with no container simply yields an error line in the pane, which is
// the honest outcome -- the page tails whatever Docker reports.
const NAMES = [
  "alice", "bob", "bb84-kme-a", "bb84-kme-b", "alice-ipsec", "bob-ipsec",
];

/**
 * Remove SGR colour codes before the log reaches the screen or an export.
 *
 * arnika writes ANSI escapes, and `/api/logs/{name}` passes the container's
 * stdout through verbatim -- the live endpoint returns, literally:
 *
 *   [INFO] \u001b[36mPRIMARY[1]\u001b[0m [OK] HKDF derivation completed
 *
 * This page's entire content is that string, so it rendered `[36mPRIMARY[1][0m`
 * as visible text, and the exported log carried the escapes into a file
 * offered as evidence. Stripping in ONE place would not have been enough: the
 * render and the export read the same state, so both are fixed by cleaning it
 * on arrival.
 *
 * Stripping rather than rendering as colour: the codes carry no information the
 * text does not already have -- arnika prefixes every line with its role
 * (PRIMARY/BACKUP) in plain text -- and a log offered as a citable artefact is
 * better as plain text.
 */
const ANSI_SGR = /\x1b\[[0-9;]*m/g;

export function stripAnsi(s: string): string {
  return s.replace(ANSI_SGR, "");
}

export default function Console() {
  const [active, setActive] = useState("alice");
  const [log, setLog] = useState("");

  useEffect(() => {
    let stop = false;
    async function loop() {
      while (!stop) {
        try {
          const r = await getLogs(active, 400);
          setLog(stripAnsi(r.log || ""));
        } catch (e) {
          setLog(`error: ${e}`);
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
        subtitle="Live tail of container stdout (Docker logs)."
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
      <div style={{ display: "flex", gap: 8, marginBottom: 12 }}>
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
