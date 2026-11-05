import { useMemo, type Ref } from "react";
import { colors } from "../lib/commonStyles";
import type { TopologyPreset } from "../lib/sim/protocolLab/publishedNetworks";
import type { RouteChoice } from "../lib/sim/protocolLab/routing";
import type { Accounting, LinkState } from "../lib/sim/protocolLabSim";
import {
  BAND_LINE_PX, COMPACT_BAND_LINE_PX, COMPACT_LABEL_FONT_PX, DOWN_MARK, EDGE_FONT_PX, EDGE_GAUGE_H,
  LABEL_FONT_PX, bandHeight, linkEnds, nodeBox, placeEdgeLabels, storeFill,
} from "../lib/sim/protocolLab/view";

/**
 * /protocol-lab's topology: this project's own schematic of a published
 * network. No coordinates are traced from a source figure (two of the sources
 * are non-commercial licences), and there is no map.
 *
 * The id is the PNG export target and must be unique in the repository.
 *
 * Order matters, because later marks cover earlier ones: the links, then their
 * captions on opaque plates (so no line strikes through the text), then the
 * nodes, then the key. Captions are placed by placeEdgeLabels, never at a bare
 * midpoint. In the compact form for a phone there are no captions, which cannot
 * fit at a readable size: the same figures are in the "Links as published" table.
 *
 * An export is this element serialised, so whatever an exported frame must show
 * has to be an attribute or a child here: the key's position, and the band under
 * the network that says it is a simulation and what the run is doing.
 */
export default function TopologyPresetSvg({
  preset, links, route, downNodes, accounting, scaleBits = null, compact = false,
  demand, previousLinks = [], atNode = null, arrived = false, noRoute = false,
  packetRef, packetLabel = null, band = [],
}: {
  preset: TopologyPreset;
  links: LinkState[];
  route: RouteChoice | null;
  downNodes: string[];
  accounting?: Accounting;
  /** Stores mode: the largest cited initial store, so every gauge shares one scale. */
  scaleBits?: number | null;
  compact?: boolean;
  demand?: { from: string; to: string };
  /** The links of the route just left, drawn for a moment after a re-route. */
  previousLinks?: string[];
  /** The trusted node holding the key in the clear right now. */
  atNode?: string | null;
  /** The key has reached the far end. */
  arrived?: boolean;
  noRoute?: boolean;
  /** Moved by the page's animation frame, outside React. Hidden until then. */
  packetRef?: Ref<SVGGElement>;
  packetLabel?: string | null;
  /** The lines of the band under the network. */
  band?: string[];
}) {
  const [W, H] = preset.viewBox;
  const places = useMemo(() => placeEdgeLabels(preset), [preset]);
  const onRoute = new Set(route?.linkIds ?? []);
  const previous = new Set(previousLinks);
  const state = (id: string) => links.find((l) => l.id === id);
  const down = links.filter((l) => l.down).map((l) => l.id);
  const label = `${preset.meta.title}. Active route: ${route ? route.nodes.join(" to ") : "none"}.`
    + (down.length ? ` Down: ${down.join(", ")}.` : "")
    + (downNodes.length ? ` Nodes down: ${downNodes.join(", ")}.` : "");
  const nodeFont = compact ? COMPACT_LABEL_FONT_PX : LABEL_FONT_PX;
  const thin = compact ? 3 : 2;
  const thick = compact ? 7 : 4;
  const bandH = band.length ? bandHeight(band.length, compact) : 0;
  const bandLine = compact ? COMPACT_BAND_LINE_PX : BAND_LINE_PX;
  return (
    <svg id="protocol-lab-topology-svg" viewBox={`0 0 ${W} ${H + bandH}`} role="img" aria-label={label}
         style={{ width: "100%", height: "auto", display: "block", background: colors.panelDark, borderRadius: 8 }}>
      {preset.links.map((l) => {
        const e = linkEnds(preset, l, nodeFont);
        const s = state(l.id);
        const stroke = s?.down ? colors.danger
          : l.kind === "non-qkd-keystore" ? colors.textMute
          : onRoute.has(l.id) ? colors.success
          : previous.has(l.id) ? colors.warn
          : s?.notInRun ? colors.border : colors.borderLt;
        const dash = s?.down ? "3 5"
          : previous.has(l.id) && !onRoute.has(l.id) ? "10 6"
          : l.kind === "non-qkd-keystore" || s?.notInRun ? "6 4" : undefined;
        return (
          <line key={l.id} x1={e.x1} y1={e.y1} x2={e.x2} y2={e.y2} stroke={stroke}
                strokeWidth={onRoute.has(l.id) || previous.has(l.id) ? thick : thin}
                strokeDasharray={dash} />
        );
      })}
      {!compact && preset.links.map((l) => {
        const p = places.get(l.id)!;
        const s = state(l.id);
        const fill = s && accounting ? storeFill(s, accounting, scaleBits) : null;
        const textY = p.cy + EDGE_FONT_PX / 3 - (fill === null ? 0 : EDGE_GAUGE_H / 2);
        const gaugeW = p.w - 8;
        return (
          <g key={l.id}>
            <rect x={p.x} y={p.y} width={p.w} height={p.h} rx={3} fill={colors.panelDark}
                  stroke={s?.down ? colors.danger : colors.border} strokeWidth={0.75} />
            <text x={p.cx} y={textY} textAnchor="middle" fontSize={EDGE_FONT_PX}
                  fill={s?.down ? colors.danger : colors.textSec}>
              {s?.down ? DOWN_MARK : ""}{p.text}
            </text>
            {fill !== null && (
              <g>
                <rect x={p.x + 4} y={p.y + p.h - EDGE_GAUGE_H - 1} width={gaugeW} height={EDGE_GAUGE_H}
                      fill={colors.border} />
                <rect x={p.x + 4} y={p.y + p.h - EDGE_GAUGE_H - 1} width={gaugeW * fill} height={EDGE_GAUGE_H}
                      fill={s?.down ? colors.danger : colors.qkd} />
              </g>
            )}
          </g>
        );
      })}
      {preset.nodes.map((n) => {
        const b = nodeBox(n, nodeFont);
        const isDown = downNodes.includes(n.id);
        const isEnd = demand && (n.id === demand.from || n.id === demand.to);
        const clear = atNode === n.id;
        return (
          <g key={n.id}>
            <rect x={b.x} y={b.y} width={b.w} height={b.h} rx={5}
                  fill={clear ? colors.active : colors.panelBg}
                  stroke={isDown ? colors.danger : clear ? colors.warn : isEnd ? colors.success : colors.accent}
                  strokeWidth={clear || isEnd ? 2.5 : 1.5} />
            <text x={n.x} y={n.y + nodeFont / 3} textAnchor="middle" fontSize={nodeFont}
                  fill={isDown ? colors.danger : colors.textPri}>{n.label}</text>
          </g>
        );
      })}
      <g ref={packetRef} visibility="hidden" style={{ pointerEvents: "none" }}>
        <circle r={compact ? 13 : 7} fill={atNode ? colors.warn : arrived ? colors.success : colors.accent}
                stroke={colors.textPri} strokeWidth={compact ? 2 : 1.25} />
        {packetLabel && !compact && (
          <text y={-16} textAnchor="middle" fontSize={EDGE_FONT_PX} fontWeight={600}
                fill={atNode ? colors.warn : arrived ? colors.success : colors.textPri}
                stroke={colors.panelDark} strokeWidth={3} paintOrder="stroke">{packetLabel}</text>
        )}
      </g>
      {noRoute && (
        <g>
          <rect x={W / 2 - (compact ? 80 : 48)} y={6} width={compact ? 160 : 96} height={compact ? 36 : 22} rx={4}
                fill={colors.panelDark} stroke={colors.danger} />
          <text x={W / 2} y={compact ? 31 : 21} textAnchor="middle" fontSize={compact ? 22 : 13} fontWeight={700}
                fill={colors.danger}>NO ROUTE</text>
        </g>
      )}
      {band.map((line, i) => (
        <text key={i} x={W / 2} y={H + bandLine * (i + 1)} textAnchor="middle" fontSize={compact ? 18 : EDGE_FONT_PX}
              fontWeight={i === 0 ? 600 : 400} fill={i === 0 ? colors.warn : colors.textSec}>{line}</text>
      ))}
    </svg>
  );
}
