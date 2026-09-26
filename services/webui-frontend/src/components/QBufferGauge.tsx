import { colors, spacing } from "../lib/commonStyles";
import { useNarrowLayout } from "../lib/layout";
import type { Accounting, LinkState } from "../lib/sim/protocolLabSim";
import { MIB_BITS } from "../lib/sim/protocolLab/publishedNetworks";

/**
 * One link's key store. What it counts depends on the accounting mode, and the
 * caption says which: keys under this repository's KeyPool rules in free play,
 * the cited MiB stores in the SECOQC replay, nothing where nothing is stated.
 */
export default function QBufferGauge({ link, accounting, keyBits, scaleBits }: {
  link: LinkState; accounting: Accounting; keyBits: number;
  /** Stores mode: the largest cited initial store, so every bar shares one scale. */
  scaleBits: number | null;
}) {
  const narrow = useNarrowLayout();
  let fill: number | null = null;
  let caption: string;
  if (accounting === "keys" && link.storedKeys !== null && link.maxKeys) {
    fill = link.storedKeys / link.maxKeys;
    caption = `stored_key_count ${link.storedKeys} / max_key_count ${link.maxKeys} (${keyBits}-bit keys); production pauses at ${link.fillToKeys} (KeyPool rule)`;
  } else if (accounting === "stores" && link.storedBits !== null && link.thresholdBits !== null) {
    const mib = link.storedBits / MIB_BITS;
    fill = scaleBits ? Math.min(1, link.storedBits / scaleBits) : null;
    caption = `${mib.toFixed(2)} MiB stored; minimum ${(link.thresholdBits / MIB_BITS).toFixed(0)} MiB (cited)`;
  } else {
    caption = accounting === "route-only" || accounting === "service-buffer"
      ? "store size not stated by the source" : link.genNote ?? "not tracked";
  }
  return (
    <div style={{ marginBottom: 8 }}>
      {/* Below the breakpoint the rate drops under the link id when both do
          not fit. Without the wrap, a downed link at 320px squeezed the two
          into side-by-side halves of about 110px and 165px, each broken over
          two lines ("CAPE-TREL / (node-down)" beside "generates 2580000
          bit/s / (reported)"; measured 2026-09-26). From 768px up the row is
          unchanged: there the halves shrink as they always have. */}
      <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12,
                    ...(narrow ? { flexWrap: "wrap", columnGap: spacing.sm } as const : {}) }}>
        <span style={{ color: link.down ? colors.danger : colors.textPri, fontFamily: "monospace" }}>
          {link.id}{link.down ? ` (${link.downReason})` : ""}
        </span>
        <span style={{ color: colors.textMute }}>
          {link.genBps === null ? "no reported rate" : `generates ${link.genBps} bit/s (reported)`}
        </span>
      </div>
      <div style={{ height: 8, background: colors.panelDark, borderRadius: 4, overflow: "hidden", margin: "3px 0" }}>
        {fill !== null && (
          <div style={{ width: `${Math.max(0, Math.min(1, fill)) * 100}%`, height: "100%",
                        background: link.down ? colors.danger : colors.qkd }} />
        )}
      </div>
      <div style={{ fontSize: 11, color: colors.textMute }}>{caption}</div>
      {link.genNote && accounting !== "keys" && (
        <div style={{ fontSize: 11, color: colors.textMute }}>{link.genNote}</div>
      )}
    </div>
  );
}
