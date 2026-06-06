import { useEffect, useState } from "react";
import { getLogs } from "../api";
import PageHeader from "../components/PageHeader";
import Button from "../components/Button";
import ExportToolbar from "../components/ExportToolbar";

const NAMES = ["alice", "bob", "bb84-kme-a", "bb84-kme-b"];

export default function Console() {
  const [active, setActive] = useState("alice");
  const [log, setLog] = useState("");

  useEffect(() => {
    let stop = false;
    async function loop() {
      while (!stop) {
        try {
          const r = await getLogs(active, 400);
          setLog(r.log || "");
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
        <ExportToolbar
          name={`console-${active}`}
          logService={active.includes("kme") ? active : "webui-backend"}
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
