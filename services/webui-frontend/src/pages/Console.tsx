import { useEffect, useState } from "react";
import { getLogs } from "../api";

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
      <h2 style={{ marginTop: 0 }}>Container Console</h2>
      <div style={{ display: "flex", gap: 8, marginBottom: 12 }}>
        {NAMES.map(n => (
          <button key={n}
                  onClick={() => setActive(n)}
                  style={{
                    background: active === n ? "#1a2440" : "#0d1320",
                    color: active === n ? "#fff" : "#9aa9d8",
                    border: "1px solid #2a3760",
                    borderRadius: 4, padding: "4px 12px",
                    fontSize: 12, cursor: "pointer",
                  }}>{n}</button>
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
