import { colors } from "../lib/commonStyles";
import type { ProtocolLabState } from "../lib/sim/protocolLabSim";

/**
 * The route controller's view: four display items and no controls.
 * Simulation only -- the running stack has no route controller.
 */
export default function SDNControlPanel({ state }: { state: ProtocolLabState }) {
  const r = state.route;
  const perLink = r ? r.linkIds.map((id) => {
    const l = state.links.find((x) => x.id === id)!;
    return { id, gen: l.genBps };
  }) : [];
  return (
    <div style={{ fontSize: 12, color: colors.textSec, lineHeight: 1.6 }}>
      <div style={{ color: colors.textPri, fontWeight: 600 }}>1. Active path</div>
      <div>
        {r ? `${r.nodes.join(" > ")} (${r.hops} hop${r.hops === 1 ? "" : "s"}, ${r.relays} relay${r.relays === 1 ? "" : "s"})`
          : `none: ${state.route_none ?? "not chosen yet"}`}
      </div>
      <div style={{ color: colors.textMute, fontSize: 11 }}>Policy: {state.policy}</div>

      <div style={{ color: colors.textPri, fontWeight: 600, marginTop: 6 }}>2. Priority</div>
      <div>QoS Priority is not set here. ETSI GS QKD 004 treats it as guidance and leaves handling to the implementation; one demand runs at a time.</div>

      <div style={{ color: colors.textPri, fontWeight: 600, marginTop: 6 }}>3. Re-routing history</div>
      {state.reroutes.length === 0 ? <div>none yet</div> : (
        <ul style={{ margin: 0, paddingLeft: 18 }}>
          {state.reroutes.slice(-6).map((x, i) => (
            <li key={i}>t = {x.t_s} s: {x.to ? x.to.join(" > ") : "no route"} ({x.reason})</li>
          ))}
        </ul>
      )}

      <div style={{ color: colors.textPri, fontWeight: 600, marginTop: 6 }}>4. Resource allocation</div>
      {perLink.length === 0 ? <div>nothing allocated</div> : (
        <ul style={{ margin: 0, paddingLeft: 18 }}>
          {perLink.map((p) => (
            <li key={p.id}>{p.id}: carries the whole demand; generates {p.gen === null ? "no reported rate" : `${p.gen} bit/s (reported)`}</li>
          ))}
        </ul>
      )}
      {state.rejected.length > 0 && (
        <div style={{ color: colors.textMute, fontSize: 11, marginTop: 4 }}>
          Not usable now: {state.rejected.map((x) => `${x.route.nodes.join(">")} (${x.why})`).join("; ")}
        </div>
      )}
    </div>
  );
}
