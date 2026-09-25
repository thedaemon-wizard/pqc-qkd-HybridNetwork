import { colors } from "../lib/commonStyles";
import type { ProtocolLabState } from "../lib/sim/protocolLabSim";

/**
 * The service-side store: the ETSI GS QKD 004 stream in free play, or
 * Cambridge's cited global key store in that scenario.
 */
export default function SBufferQueue({ state }: { state: ProtocolLabState }) {
  if (state.service) {
    const s = state.service;
    return (
      <div style={{ fontSize: 12, color: colors.textSec, lineHeight: 1.6 }}>
        <div>Global key store: <b style={{ color: colors.textPri }}>{s.stored}</b> / {s.capacity} keys</div>
        <div>Refilled to {s.refillTo} when it falls to {s.refillAt} (cited)</div>
        <div>Refills: {s.refills}; failed refills: {s.failedRefills}</div>
        <div style={{ color: colors.textMute, fontSize: 11 }}>{s.readingNote}</div>
      </div>
    );
  }
  if (state.stream) {
    const s = state.stream;
    return (
      <div style={{ fontSize: 12, color: colors.textSec, lineHeight: 1.6 }}>
        <div>Key_stream_ID <code>{s.ksid?.slice(0, 8)}...</code> ({s.state})</div>
        <div>Undelivered chunks: <b style={{ color: colors.textPri }}>{s.undelivered}</b>; next index {s.next_index}</div>
        <div>Key_chunk_size {s.key_chunk_bytes} bytes; delivered {s.delivered}</div>
        <div>Last GET_KEY status: {s.last_status ?? "none yet"}</div>
        <div style={{ color: colors.textMute, fontSize: 11 }}>
          Refilled by relay whenever it holds fewer chunks than the KeyPool low watermark.
        </div>
      </div>
    );
  }
  return (
    <div style={{ fontSize: 12, color: colors.textMute }}>
      No service-side store in this {state.scenario_id ? "scenario" : "mode"}: the demand draws on the link stores directly.
    </div>
  );
}
