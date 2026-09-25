import { colors } from "../lib/commonStyles";
import type { TopologyPreset } from "../lib/sim/protocolLab/publishedNetworks";
import type { RouteChoice } from "../lib/sim/protocolLab/routing";
import type { LinkState } from "../lib/sim/protocolLabSim";
import { LABEL_FONT_PX, edgeLabel, midpoint, nodeBox } from "../lib/sim/protocolLab/view";

/**
 * /protocol-lab's topology: this project's own schematic of a published
 * network. No coordinates are traced from a source figure (two of the sources
 * are non-commercial licences), and there is no map.
 *
 * The id is the PNG export target and must be unique in the repository.
 */
export default function TopologyPresetSvg({ preset, links, route, downNodes }: {
  preset: TopologyPreset;
  links: LinkState[];
  route: RouteChoice | null;
  downNodes: string[];
}) {
  const [W, H] = preset.viewBox;
  const onRoute = new Set(route?.linkIds ?? []);
  const state = (id: string) => links.find((l) => l.id === id);
  const down = links.filter((l) => l.down).map((l) => l.id);
  const label = `${preset.meta.title}. Active route: ${route ? route.nodes.join(" to ") : "none"}.`
    + (down.length ? ` Down: ${down.join(", ")}.` : "")
    + (downNodes.length ? ` Nodes down: ${downNodes.join(", ")}.` : "");
  return (
    <svg id="protocol-lab-topology-svg" viewBox={`0 0 ${W} ${H}`} role="img" aria-label={label}
         style={{ width: "100%", height: "auto", background: colors.panelDark, borderRadius: 8 }}>
      {preset.links.map((l) => {
        const a = preset.nodes.find((n) => n.id === l.a)!;
        const b = preset.nodes.find((n) => n.id === l.b)!;
        const s = state(l.id);
        const stroke = s?.down ? colors.danger
          : l.kind === "non-qkd-keystore" ? colors.textMute
          : onRoute.has(l.id) ? colors.success
          : s?.notInRun ? colors.border : colors.borderLt;
        const m = midpoint(preset, l);
        return (
          <g key={l.id}>
            <line x1={a.x} y1={a.y} x2={b.x} y2={b.y} stroke={stroke}
                  strokeWidth={onRoute.has(l.id) ? 4 : 2}
                  strokeDasharray={l.kind === "non-qkd-keystore" || s?.notInRun ? "6 4" : undefined} />
            <text x={m.x} y={m.y - 6} textAnchor="middle" fontSize={10} fill={colors.textSec}>
              {edgeLabel(l)}
            </text>
          </g>
        );
      })}
      {preset.nodes.map((n) => {
        const b = nodeBox(n);
        const isDown = downNodes.includes(n.id);
        return (
          <g key={n.id}>
            <rect x={b.x} y={b.y} width={b.w} height={b.h} rx={5}
                  fill={colors.panelBg} stroke={isDown ? colors.danger : colors.accent} strokeWidth={1.5} />
            <text x={n.x} y={n.y + LABEL_FONT_PX / 3} textAnchor="middle" fontSize={LABEL_FONT_PX}
                  fill={isDown ? colors.danger : colors.textPri}>{n.label}</text>
          </g>
        );
      })}
    </svg>
  );
}
