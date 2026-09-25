/**
 * Route selection for trusted-node key relay on a published topology.
 *
 * Relay spends the same key on every hop, so what a path can carry is set by
 * its weakest hop (the bottleneck), not by a sum of lengths or losses; an
 * additive cost would model nothing real here.
 *
 * The ranking -- fewest hops first, then the widest bottleneck in stored bits,
 * then the widest bottleneck in rate, then a stable id -- is THIS PROJECT'S
 * INFERENCE. None of the sources states its routing metric. It was chosen
 * because it reproduces SECOQC's published route order (section 5.1.2), where
 * pure widest-bottleneck routing would have picked FOR-ERD-SIE-BRT first; that
 * makes the SECOQC replay a consistency check, not independent evidence.
 * Cambridge's automatic switch back to the direct link after an outage is the
 * independent check. Each relay is another trusted node that holds the key in
 * the clear, which is a second reason to prefer fewer hops.
 *
 * No max-flow and no multiple demands in this release (docs/roadmap.md).
 */

export interface RouteGraph {
  nodes: readonly string[];
  links: readonly { id: string; a: string; b: string }[];
}

/** What one link offers a route right now. */
export interface LinkView {
  /** Down links are removed from the graph before paths are enumerated. */
  up: boolean;
  /** Up but unable to carry this request, with the reason. */
  usable: boolean;
  why?: string;
  /** Bits available above any threshold, or null when not tracked. */
  availableBits: number | null;
  /** Generation rate in bit/s, or null when not reported. */
  rateBps: number | null;
}

export interface RouteChoice {
  nodes: string[];
  linkIds: string[];
  hops: number;
  /** Trusted nodes between the endpoints -- ETSI GS QKD 004 metadata "hops". */
  relays: number;
  bottleneckBits: number | null;
  bottleneckBps: number | null;
}

/** Safety bound on enumeration. No shipped preset comes near it (routing.test.ts). */
export const MAX_SIMPLE_PATHS = 64;

export const ROUTING_POLICY =
  "fewest hops, then widest bottleneck (this project's inference; the sources do not state a metric)";

/** Every simple path from `src` to `dst` avoiding down nodes and links. */
export function simplePaths(
  g: RouteGraph, src: string, dst: string,
  down: { nodes: ReadonlySet<string>; links: ReadonlySet<string> } = { nodes: new Set(), links: new Set() },
): { nodes: string[]; linkIds: string[] }[] {
  if (down.nodes.has(src) || down.nodes.has(dst) || src === dst) return [];
  const adj = new Map<string, { to: string; id: string }[]>();
  for (const n of g.nodes) adj.set(n, []);
  for (const l of g.links) {
    if (down.links.has(l.id) || down.nodes.has(l.a) || down.nodes.has(l.b)) continue;
    adj.get(l.a)?.push({ to: l.b, id: l.id });
    adj.get(l.b)?.push({ to: l.a, id: l.id });
  }
  const out: { nodes: string[]; linkIds: string[] }[] = [];
  const walk = (at: string, nodes: string[], linkIds: string[]) => {
    if (out.length >= MAX_SIMPLE_PATHS) return;
    if (at === dst) { out.push({ nodes: [...nodes], linkIds: [...linkIds] }); return; }
    for (const e of adj.get(at) ?? []) {
      if (nodes.includes(e.to)) continue;
      nodes.push(e.to); linkIds.push(e.id);
      walk(e.to, nodes, linkIds);
      nodes.pop(); linkIds.pop();
    }
  };
  walk(src, [src], []);
  return out;
}

function minOrNull(xs: (number | null)[]): number | null {
  const known = xs.filter((x): x is number => x !== null);
  // One unknown hop makes the whole bottleneck unknown: a minimum over the
  // known hops would overstate a path whose weakest hop is the unreported one.
  return known.length === xs.length && known.length > 0 ? Math.min(...known) : null;
}

export function describeRoute(
  path: { nodes: string[]; linkIds: string[] }, view: (id: string) => LinkView,
): RouteChoice {
  const views = path.linkIds.map(view);
  return {
    nodes: path.nodes, linkIds: path.linkIds,
    hops: path.linkIds.length, relays: Math.max(0, path.linkIds.length - 1),
    bottleneckBits: minOrNull(views.map((v) => v.availableBits)),
    bottleneckBps: minOrNull(views.map((v) => v.rateBps)),
  };
}

const desc = (a: number | null, b: number | null) =>
  a === null && b === null ? 0 : a === null ? 1 : b === null ? -1 : b - a;

export function rankRoutes(routes: RouteChoice[]): RouteChoice[] {
  return [...routes].sort((x, y) =>
    x.hops - y.hops
    || desc(x.bottleneckBits, y.bottleneckBits)
    || desc(x.bottleneckBps, y.bottleneckBps)
    || x.linkIds.join(",").localeCompare(y.linkIds.join(",")));
}

export const routeKey = (nodes: readonly string[]) => nodes.join("-");

export interface Selection {
  chosen: RouteChoice | null;
  ranked: RouteChoice[];
  rejected: { route: RouteChoice; why: string }[];
  /** Why there is no route at all, when `chosen` is null. */
  none?: string;
}

export function selectRoute(
  g: RouteGraph, src: string, dst: string, view: (id: string) => LinkView,
  opts: { downNodes?: ReadonlySet<string>; preferred?: readonly string[] } = {},
): Selection {
  const downLinks = new Set(g.links.filter((l) => !view(l.id).up).map((l) => l.id));
  const downNodes = opts.downNodes ?? new Set<string>();
  if (downNodes.has(src) || downNodes.has(dst)) {
    return { chosen: null, ranked: [], rejected: [], none: `endpoint ${downNodes.has(src) ? src : dst} is down` };
  }
  const paths = simplePaths(g, src, dst, { nodes: downNodes, links: downLinks });
  if (paths.length === 0) return { chosen: null, ranked: [], rejected: [], none: "no path of working links" };

  const usable: RouteChoice[] = [];
  const rejected: { route: RouteChoice; why: string }[] = [];
  for (const p of paths) {
    const r = describeRoute(p, view);
    const blocked = p.linkIds.map((id) => ({ id, v: view(id) })).find(({ v }) => !v.usable);
    if (blocked) rejected.push({ route: r, why: `${blocked.id}: ${blocked.v.why ?? "unusable"}` });
    else usable.push(r);
  }
  const ranked = rankRoutes(usable);
  const pref = opts.preferred ? ranked.find((r) => routeKey(r.nodes) === routeKey(opts.preferred!)) : undefined;
  const chosen = pref ?? ranked[0] ?? null;
  rejected.sort((x, y) => x.route.hops - y.route.hops
    || routeKey(x.route.nodes).localeCompare(routeKey(y.route.nodes)));
  return {
    chosen, ranked, rejected,
    none: chosen ? undefined : "every path has a hop that cannot carry the request",
  };
}
