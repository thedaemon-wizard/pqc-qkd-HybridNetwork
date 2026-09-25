/**
 * Client-side Protocol Lab simulator: trusted-node key relay over a published
 * topology, with this repository's ETSI GS QKD 014 message shapes per hop and
 * a simulated ETSI GS QKD 004 V2.1.1 stream end to end.
 *
 * SIMULATION. Every value is computed in the browser from the published
 * numbers in protocolLab/publishedNetworks.ts; nothing is observed from the
 * running stack, which keys each hop independently and relays nothing.
 *
 * Four accounting modes, chosen by the preset or scenario, each saying what it
 * counts:
 *   keys           -- free play. Each link generates at its REPORTED rate into
 *                     a buffer following this repository's KeyPool rules
 *                     (unit out_bits_per_key; production pauses at
 *                     pool_low_watermark; hard bound pool_max_size), and a
 *                     relayed key costs one key on every hop.
 *   stores         -- SECOQC: the cited per-link stores and threshold, in bits.
 *   service-buffer -- Cambridge: the cited 1000-key global store refilled by
 *                     relay when it falls to 800.
 *   route-only     -- rates or stores not available: routes chosen by which
 *                     links are up; nothing counted.
 *
 * Status and step semantics are PaperSim's, and paperStepIsNotIdle.test.ts
 * holds the three simulators to one status union.
 */
import { BUNDLED_PARAMS } from "./keyrate";
import { randomBytes, toHex } from "./crypto";
import { RunSeeds } from "./runSeed";
import {
  presetById, scenarioById, quantityValue,
  type FailureTarget, type PresetLink, type Scenario, type TopologyPreset,
} from "./protocolLab/publishedNetworks";
import {
  ROUTING_POLICY, routeKey, selectRoute,
  type LinkView, type RouteChoice, type RouteGraph,
} from "./protocolLab/routing";
import {
  EMPTY_QOS, INDEX_ORIGIN, Km004, SPEC_VERSION, statusById, statusCode,
  type CallResult, type StatusId,
} from "./protocolLab/etsi004";
import { ETSI014_THIS_REPO } from "./protocolLab/etsi014Shapes";

/**
 * UI dwell per simulated tick. Distinct from /e2e (450) and /paper-flow (350),
 * and exported in the CSV as `nominal_dwell_ms` for the same reason as theirs:
 * the measured dwell is wall-clock and a hidden tab throttles it.
 */
export const NOMINAL_TICK_DWELL_MS = 250;
/** Free play's tick: a resolution, not physics. */
export const FREE_PLAY_TICK_S = 1;
/** Covers the 180-tick SECOQC replay with room to spare. */
export const HISTORY_LIMIT = 500;
export const MESSAGE_LIMIT = 60;
/** Characters of hex kept from any key or pad: a fingerprint, never the key. */
export const PREFIX_HEX = 16;

export type Accounting = "keys" | "stores" | "service-buffer" | "route-only";
export type SimStatus = ProtocolLabState["status"];

export interface LinkState {
  id: string;
  a: string;
  b: string;
  kind: PresetLink["kind"];
  down: boolean;
  downReason: "outage" | "qber-alarm" | "node-down" | null;
  notInRun: boolean;
  /** Reported rate in bit/s, or null. */
  genBps: number | null;
  genNote: string | null;
  /** keys accounting */
  storedKeys: number | null;
  fillToKeys: number | null;
  maxKeys: number | null;
  /** stores accounting */
  storedBits: number | null;
  thresholdBits: number | null;
}

export interface TimelineMessage {
  t_s: number;
  lane: "014" | "004";
  text: string;
  status?: number | null;
  http?: number;
  transition?: string;
}

export interface TickRec {
  tick: number;
  sim_time_s: number;
  started_at: number;
  ui_dwell_ms: number | "";
  route: string;
  relays: number | "";
  delivered_bits: number;
  unmet_bits: number;
  event: string;
  buffers: Record<string, number | null>;
}

export interface Reroute {
  t_s: number;
  from: string[] | null;
  to: string[] | null;
  reason: "start" | "threshold" | "link-down" | "node-down" | "qber-alarm" | "recovered" | "no-route";
}

export interface ProtocolLabState {
  status: "idle" | "running" | "paused" | "stepped";
  preset_id: string;
  scenario_id: string | null;
  accounting: Accounting;
  accounting_why: string;
  tick: number;
  tick_s: number;
  sim_time_s: number;
  demand: { from: string; to: string; label: string; source: string;
            bps: number | null; keysPerS: number | null };
  links: LinkState[];
  down_nodes: string[];
  route: RouteChoice | null;
  route_none: string | null;
  alternatives: RouteChoice[];
  rejected: { route: RouteChoice; why: string }[];
  reroutes: Reroute[];
  delivered_bits: number;
  unmet_bits: number;
  requests_ok: number;
  requests_failed: number;
  service: { stored: number; capacity: number; refillAt: number; refillTo: number;
             refills: number; failedRefills: number; readingNote: string } | null;
  stream: { ksid: string | null; state: string; next_index: number; undelivered: number;
            delivered: number; key_chunk_bytes: number; last_status: number | null } | null;
  messages: TimelineMessage[];
  last_relay: { hops: number; key_prefix: string; pad_prefixes: string[];
                recovered_equals_sent: boolean } | null;
  history: TickRec[];
  published: Scenario["published"] | null;
  limits: string[];
  policy: string;
  key_bits: number;
  key_bits_source: string;
  seed: number | null;
  seed_pinned: boolean;
  nominal_dwell_ms: number;
  engine: string;
  spec: string;
}

/** CSV rows for the export. `nominal_dwell_ms` beside the measured dwell. */
export function protocolLabCsvRows(state: ProtocolLabState): Record<string, unknown>[] {
  return state.history.map((h) => {
    const row: Record<string, unknown> = {
      tick: h.tick, sim_time_s: h.sim_time_s,
      started_at: new Date(h.started_at).toISOString(),
      ui_dwell_ms: h.ui_dwell_ms, nominal_dwell_ms: NOMINAL_TICK_DWELL_MS,
      preset: state.preset_id, scenario: state.scenario_id ?? "",
      accounting: state.accounting,
      demand: `${state.demand.from}->${state.demand.to}`,
      route: h.route, relays: h.relays,
      delivered_bits: h.delivered_bits, unmet_bits: h.unmet_bits, event: h.event,
    };
    for (const [id, v] of Object.entries(h.buffers)) row[`buf_${id}`] = v ?? "";
    return row;
  });
}

const KEY_BITS: number = BUNDLED_PARAMS.outBitsPerKey;
const KEY_BYTES = KEY_BITS / 8;
const LOW_WM: number = BUNDLED_PARAMS.poolLowWatermark;
const MAX_KEYS: number = BUNDLED_PARAMS.poolMaxSize;
const KEY_BITS_SOURCE = "protocol.out_bits_per_key (this project's config)";

const reasonFor = (l: LinkState): Reroute["reason"] =>
  l.downReason === "qber-alarm" ? "qber-alarm" : l.downReason === "node-down" ? "node-down" : "link-down";

export class ProtocolLabSim {
  private status: SimStatus = "idle";
  private readonly onState: (s: ProtocolLabState) => void;
  private readonly seeds: RunSeeds;
  private readonly newKsid: () => string;
  private timer: number | null = null;
  private lastAdvance = 0;
  private lastTickStart: number | null = null;

  private preset!: TopologyPreset;
  private scenario: Scenario | null = null;
  private accounting: Accounting = "keys";
  private tickS = FREE_PLAY_TICK_S;
  private tickN = 0;
  private links: LinkState[] = [];
  private downNodes = new Set<string>();
  private credit = new Map<string, number>();
  private demandFrom = "";
  private demandTo = "";
  private keysPerS: number | null = 1;
  private demandCredit = 0;
  private route: RouteChoice | null = null;
  private routeNone: string | null = null;
  private alternatives: RouteChoice[] = [];
  private rejected: { route: RouteChoice; why: string }[] = [];
  private reroutes: Reroute[] = [];
  private delivered = 0;
  private unmet = 0;
  private ok = 0;
  private failed = 0;
  private service: ProtocolLabState["service"] = null;
  private km!: Km004;
  private ksid: string | null = null;
  private lastStatus: number | null = null;
  private messages: TimelineMessage[] = [];
  private lastRelay: ProtocolLabState["last_relay"] = null;
  private history: TickRec[] = [];
  private pendingEvent: string[] = [];

  constructor(onState: (s: ProtocolLabState) => void,
              opts: { seeds?: RunSeeds; newKsid?: () => string; presetId?: string } = {}) {
    this.onState = onState;
    this.seeds = opts.seeds ?? RunSeeds.fromLocation();
    this.newKsid = opts.newKsid ?? (() => crypto.randomUUID());
    this.load(opts.presetId ?? "cambridge-2019", null);
    this.emit();
  }

  // ---- public controls ---------------------------------------------------
  snapshot(): ProtocolLabState {
    const stream = this.ksid === null ? null : (() => {
      const s = this.km.list().find((x) => x.ksid === this.ksid);
      return s ? {
        ksid: this.ksid, state: s.state, next_index: INDEX_ORIGIN + s.delivered.A,
        undelivered: s.chunks - s.delivered.A, delivered: s.delivered.A,
        key_chunk_bytes: this.km.chunkBytes(this.ksid) ?? KEY_BYTES, last_status: this.lastStatus,
      } : null;
    })();
    const d = this.scenario?.demand;
    return {
      status: this.status,
      preset_id: this.preset.meta.id,
      scenario_id: this.scenario?.id ?? null,
      accounting: this.accounting,
      accounting_why: this.scenario ? this.scenario.summary : this.preset.freePlay.why,
      tick: this.tickN, tick_s: this.tickS, sim_time_s: this.tickN * this.tickS,
      demand: {
        from: this.demandFrom, to: this.demandTo,
        label: d ? `${d.rate.qualifier ? d.rate.qualifier + " " : ""}${d.rate.printed} ${d.rate.unit}` : `${this.keysPerS ?? 0} key requests/s`,
        source: d ? d.rate.ref : "set on this page; not from the source",
        bps: d && d.rate.unit !== "keys/s" ? quantityValue(d.rate) : null,
        keysPerS: d && d.rate.unit === "keys/s" ? quantityValue(d.rate) : (d ? null : this.keysPerS),
      },
      links: this.links.map((l) => ({ ...l })),
      down_nodes: [...this.downNodes],
      route: this.route, route_none: this.routeNone,
      alternatives: this.alternatives, rejected: this.rejected,
      reroutes: [...this.reroutes],
      delivered_bits: this.delivered, unmet_bits: this.unmet,
      requests_ok: this.ok, requests_failed: this.failed,
      service: this.service ? { ...this.service } : null,
      stream,
      messages: [...this.messages],
      last_relay: this.lastRelay ? { ...this.lastRelay, pad_prefixes: [...this.lastRelay.pad_prefixes] } : null,
      history: [...this.history],
      published: this.scenario?.published ?? null,
      limits: this.scenario?.limits ?? [],
      policy: ROUTING_POLICY,
      key_bits: KEY_BITS, key_bits_source: KEY_BITS_SOURCE,
      seed: this.seeds.value, seed_pinned: this.seeds.pinned,
      nominal_dwell_ms: NOMINAL_TICK_DWELL_MS,
      engine: "client-side (JS)",
      spec: SPEC_VERSION,
    };
  }

  start() { this.status = "running"; this.ensureLoop(); this.emit(); }
  pause() { this.status = "paused"; this.stopLoop(); this.emit(); }
  resume() { this.status = "running"; this.ensureLoop(); this.emit(); }

  /** One tick, from idle or paused. Refuses while running, as PaperSim does. */
  step() {
    if (this.status === "running") return;
    const before = this.status;
    this.status = "stepped";
    this.advance();
    if (before === "paused") this.status = "paused";
    this.emit();
  }

  reset() {
    this.stopLoop();
    this.status = "idle";
    this.load(this.preset.meta.id, this.scenario?.id ?? null);
    this.emit();
  }

  dispose() { this.stopLoop(); this.clearKeyMaterial(); }

  loadPreset(presetId: string, scenarioId: string | null) {
    this.stopLoop();
    this.status = "idle";
    this.load(presetId, scenarioId);
    this.emit();
  }

  /** Free play only: the endpoints and the request rate. */
  setDemand(from: string, to: string, keysPerS: number) {
    if (this.scenario) return;
    this.demandFrom = from; this.demandTo = to;
    this.keysPerS = Number.isFinite(keysPerS) && keysPerS >= 0 ? keysPerS : 0;
    this.stopLoop();
    this.status = "idle";
    this.load(this.preset.meta.id, null, { from, to, keysPerS: this.keysPerS });
    this.emit();
  }

  injectFailure(t: FailureTarget) {
    if (t.kind === "link") {
      const l = this.links.find((x) => x.id === t.id);
      if (!l) return;
      l.down = true; l.downReason = t.reason ?? "outage";
      this.pendingEvent.push(`${l.id} ${l.downReason}`);
    } else {
      this.downNodes.add(t.id);
      for (const l of this.links) if (l.a === t.id || l.b === t.id) { l.down = true; l.downReason = "node-down"; }
      this.pendingEvent.push(`node ${t.id} down`);
    }
    this.chooseRoute();
    this.emit();
  }

  clearFailure(t?: FailureTarget) {
    if (!t) {
      for (const l of this.links) { l.down = false; l.downReason = null; }
      this.downNodes.clear();
      this.pendingEvent.push("all failures cleared");
    } else if (t.kind === "link") {
      const l = this.links.find((x) => x.id === t.id);
      if (!l) return;
      l.down = this.downNodes.has(l.a) || this.downNodes.has(l.b);
      l.downReason = l.down ? "node-down" : null;
      this.pendingEvent.push(`${t.id} restored`);
    } else {
      this.downNodes.delete(t.id);
      for (const l of this.links) {
        if ((l.a === t.id || l.b === t.id) && l.downReason === "node-down"
            && !this.downNodes.has(l.a) && !this.downNodes.has(l.b)) { l.down = false; l.downReason = null; }
      }
      this.pendingEvent.push(`node ${t.id} restored`);
    }
    this.chooseRoute();
    this.emit();
  }

  /** A pseudo-random link outage; `?seed=` pins which. */
  injectRandomFailure(): FailureTarget | null {
    const candidates = this.links.filter((l) => l.kind === "qkd" && !l.down && !l.notInRun);
    const seed = this.seeds.next();
    if (candidates.length === 0) return null;
    const pick = candidates[seed % candidates.length];
    const t: FailureTarget = { kind: "link", id: pick.id, reason: "outage" };
    this.injectFailure(t);
    return t;
  }

  // ---- setup --------------------------------------------------------------
  private load(presetId: string, scenarioId: string | null,
               free?: { from: string; to: string; keysPerS: number }) {
    this.clearKeyMaterial();
    this.preset = presetById(presetId);
    this.scenario = scenarioId ? scenarioById(scenarioId) : null;
    if (this.scenario && this.scenario.presetId !== presetId) {
      throw new Error(`scenario ${scenarioId} belongs to ${this.scenario.presetId}`);
    }
    const sc = this.scenario;
    this.accounting = sc ? sc.accounting : this.preset.freePlay.accounting;
    this.tickS = sc ? sc.tick.seconds : FREE_PLAY_TICK_S;
    this.tickN = 0;
    this.demandFrom = sc ? sc.demand.from : free?.from ?? this.preset.defaultDemand.from;
    this.demandTo = sc ? sc.demand.to : free?.to ?? this.preset.defaultDemand.to;
    if (free) this.keysPerS = free.keysPerS;
    this.demandCredit = 0;
    this.downNodes = new Set();
    this.credit = new Map();
    this.route = null; this.routeNone = null; this.alternatives = []; this.rejected = [];
    this.reroutes = []; this.delivered = 0; this.unmet = 0; this.ok = 0; this.failed = 0;
    this.messages = []; this.history = []; this.pendingEvent = []; this.lastRelay = null;
    this.lastStatus = null; this.lastTickStart = null;
    this.seeds.reset();

    const notInRun = new Set(sc?.notInRun?.linkIds ?? []);
    this.links = this.preset.links.map((l) => {
      const genBps = l.rate ? quantityValue(l.rate) : null;
      const st: LinkState = {
        id: l.id, a: l.a, b: l.b, kind: l.kind, down: false, downReason: null,
        notInRun: notInRun.has(l.id),
        genBps,
        genNote: l.kind !== "qkd" ? "keystore hop, not QKD: never routed"
          : genBps === null ? "no single reported rate: generates nothing here" : null,
        storedKeys: null, fillToKeys: null, maxKeys: null, storedBits: null, thresholdBits: null,
      };
      if (this.accounting === "keys" && l.kind === "qkd") {
        st.storedKeys = 0; st.fillToKeys = LOW_WM; st.maxKeys = MAX_KEYS;
      }
      if (sc?.accounting === "stores") {
        const init = sc.stores[l.id];
        st.storedBits = init ? quantityValue(init) : null;
        st.thresholdBits = init ? quantityValue(sc.threshold) : null;
        const g = sc.generation[l.id];
        st.genNote = !g ? (st.notInRun ? "not part of the cited run" : "no store in the cited run")
          : g.kind === "equals-demand" ? `generates as fast as the demand for the first ${g.until.printed} ${g.until.unit} (${g.until.ref})`
          : g.kind === "none" ? "not generating (source)"
          : "generating, rate not given by the source: replayed as zero, so its route lifetime is a lower bound";
      }
      return st;
    });

    this.service = sc?.accounting === "service-buffer" ? {
      stored: quantityValue(sc.serviceBuffer.capacity),
      capacity: quantityValue(sc.serviceBuffer.capacity),
      refillAt: quantityValue(sc.serviceBuffer.refillAt),
      refillTo: quantityValue(sc.serviceBuffer.refillTo),
      refills: 0, failedRefills: 0, readingNote: sc.serviceBuffer.readingNote,
    } : null;

    this.km = new Km004({
      keyChunkBytes: KEY_BYTES,
      routeUp: () => this.route !== null,
      capacity: () => ({ bps: this.route?.bottleneckBps ?? null, basis: "reported rates, bottleneck of the current route" }),
      now: () => this.tickN * this.tickS * 1000,
      newKsid: this.newKsid,
    });
    this.ksid = null;
    this.chooseRoute();
    if (this.accounting === "keys") this.openStream();
  }

  // ---- the tick -------------------------------------------------------------
  private advance() {
    const now = Date.now();
    const dwell: number | "" = this.lastTickStart === null ? "" : now - this.lastTickStart;
    this.lastTickStart = now;
    this.tickN += 1;
    const t = this.tickN * this.tickS;
    const events = this.pendingEvent.splice(0);
    let deliveredNow = 0;
    let unmetNow = 0;

    if (this.accounting === "keys") {
      this.generateKeys();
      if (this.ksid === null || !this.km.isEstablished(this.ksid)) this.openStream();
      this.chooseRoute();
      this.refillStream();
      const r = this.consumeStream();
      deliveredNow = r.delivered; unmetNow = r.unmet;
    } else if (this.accounting === "stores") {
      const sc = this.scenario as Extract<Scenario, { accounting: "stores" }>;
      const need = quantityValue(sc.demand.rate) * this.tickS;
      for (const l of this.links) {
        const g = sc.generation[l.id];
        if (g?.kind === "equals-demand" && t <= quantityValue(g.until) && l.storedBits !== null) l.storedBits += need;
      }
      this.chooseRoute(need);
      if (this.route) {
        for (const id of this.route.linkIds) {
          const l = this.links.find((x) => x.id === id)!;
          l.storedBits = (l.storedBits ?? 0) - need;
        }
        deliveredNow = need;
        this.relaySample();
        this.log("014", `per hop over ${routeKey(this.route.nodes)}: enc_keys/dec_keys for ${need} bits (${ETSI014_THIS_REPO.sizeUnit})`);
      } else {
        unmetNow = need;
        this.log("004", "GET_KEY: no route of stores above threshold", this.km4Status("NO_QKD_CONNECTION"));
      }
    } else if (this.accounting === "service-buffer") {
      const sc = this.scenario as Extract<Scenario, { accounting: "service-buffer" }>;
      const svc = this.service!;
      const draw = quantityValue(sc.demand.rate) * this.tickS;
      this.demandCredit += draw;
      const whole = Math.floor(this.demandCredit);
      this.demandCredit -= whole;
      const served = Math.min(whole, svc.stored);
      svc.stored -= served;
      this.ok += served; this.failed += whole - served;
      deliveredNow = served * KEY_BITS; unmetNow = (whole - served) * KEY_BITS;
      if (svc.stored <= svc.refillAt) {
        const keys = svc.refillTo - svc.stored;
        this.chooseRoute(keys * KEY_BITS);
        if (this.route) {
          svc.stored = svc.refillTo; svc.refills += 1;
          this.relaySample();
          this.log("014", `refill ${keys} keys over ${routeKey(this.route.nodes)} (one-time-pad tunnels; ${keys * KEY_BITS} bits at ${KEY_BITS} bits per key from ${KEY_BITS_SOURCE})`);
        } else {
          svc.failedRefills += 1;
          this.log("014", `refill of ${keys} keys failed: ${this.routeNone ?? "no route"}`);
        }
      } else {
        this.chooseRoute(0);
      }
    } else {
      this.chooseRoute();
    }

    this.delivered += deliveredNow;
    this.unmet += unmetNow;
    const rec: TickRec = {
      tick: this.tickN, sim_time_s: t, started_at: now, ui_dwell_ms: dwell,
      route: this.route ? routeKey(this.route.nodes) : "",
      relays: this.route ? this.route.relays : "",
      delivered_bits: deliveredNow, unmet_bits: unmetNow,
      event: events.join("; "),
      buffers: Object.fromEntries(this.links.map((l) => [l.id,
        this.accounting === "stores" ? l.storedBits : this.accounting === "keys" ? l.storedKeys : null])),
    };
    this.history.push(rec);
    if (this.history.length > HISTORY_LIMIT) this.history.shift();

    // The cited SECOQC run ends when no route is left: halt there, the way
    // PaperSim reports a halted run.
    if (this.accounting === "stores" && this.route === null && this.status === "running") {
      this.status = "paused";
      this.stopLoop();
    }
  }

  private generateKeys() {
    for (const l of this.links) {
      if (l.kind !== "qkd" || l.down || l.genBps === null || l.storedKeys === null) continue;
      // KeyPool's producer gate: production runs only below the low watermark
      // (services/bb84-kme/app/keypool.py), so credit does not bank while full.
      if (l.storedKeys >= LOW_WM) { this.credit.set(l.id, 0); continue; }
      const c = (this.credit.get(l.id) ?? 0) + (l.genBps * this.tickS) / KEY_BITS;
      const made = Math.min(Math.floor(c), LOW_WM - l.storedKeys, MAX_KEYS - l.storedKeys);
      l.storedKeys += made;
      this.credit.set(l.id, l.storedKeys >= LOW_WM ? 0 : c - made);
    }
  }

  private openStream() {
    if (this.demandFrom === this.demandTo) return;
    const src = `qkd://${this.demandFrom}/app`, dst = `qkd://${this.demandTo}/app`;
    const a = this.km.openConnect("A", src, dst, { ...EMPTY_QOS }, null);
    this.log004("OPEN_CONNECT (A, Key_stream_ID null)", a);
    if (a.status !== this.km4Status("PEER_NOT_CONNECTED") || !a.Key_stream_ID) return;
    this.ksid = a.Key_stream_ID;
    const b = this.km.openConnect("B", dst, src, { ...EMPTY_QOS }, this.ksid);
    this.log004("OPEN_CONNECT (B, same Key_stream_ID)", b);
  }

  /** Relay keys into the 004 stream until it holds pool_low_watermark undelivered chunks. */
  private refillStream() {
    if (this.ksid === null || !this.km.isEstablished(this.ksid) || !this.route) return;
    let relayed = 0;
    let waiting: string | null = null;
    while (this.km.undelivered(this.ksid, "A") < LOW_WM) {
      this.chooseRoute();
      if (!this.route) break;
      if ((this.route.bottleneckBits ?? 0) < KEY_BITS) {
        const empty = this.route.linkIds.find((id) => (this.links.find((x) => x.id === id)!.storedKeys ?? 0) < 1);
        waiting = `waiting for key on ${empty}`;
        break;
      }
      for (const id of this.route.linkIds) {
        const l = this.links.find((x) => x.id === id)!;
        l.storedKeys = (l.storedKeys ?? 0) - 1;
      }
      const key = this.relaySample();
      this.km.supply(this.ksid, key, this.route.relays);
      key.fill(0);
      relayed += 1;
    }
    if (relayed > 0 && this.route) {
      this.log("014", `${relayed} key(s) relayed over ${routeKey(this.route.nodes)}: per hop enc_keys + dec_keys, size ${KEY_BITS} ${ETSI014_THIS_REPO.sizeUnit}`);
    } else if (waiting) {
      this.log("014", `no relay this tick: ${waiting} (enc_keys on an empty pool is HTTP ${ETSI014_THIS_REPO.http.poolEmpty} on this stack)`);
    } else if (this.route === null && this.routeNone) {
      this.log("014", `no relay: ${this.routeNone} (a KME with an empty pool answers enc_keys with HTTP ${ETSI014_THIS_REPO.http.poolEmpty})`);
    }
  }

  private consumeStream(): { delivered: number; unmet: number } {
    this.demandCredit += (this.keysPerS ?? 0) * this.tickS;
    const n = Math.floor(this.demandCredit);
    this.demandCredit -= n;
    if (n === 0) return { delivered: 0, unmet: 0 };
    if (this.ksid === null) {
      this.failed += n;
      this.lastStatus = this.km4Status("NO_QKD_CONNECTION");
      this.log("004", `GET_KEY x${n}: no stream (OPEN_CONNECT has not succeeded)`, this.lastStatus);
      return { delivered: 0, unmet: n * KEY_BITS };
    }
    let okN = 0, lastFail: CallResult | null = null, first = -1, last = -1;
    for (let i = 0; i < n; i++) {
      const a = this.km.getKey("A", this.ksid, null, 0);
      if (a.status !== this.km4Status("SUCCESSFUL")) { lastFail = a; break; }
      const b = this.km.getKey("B", this.ksid, a.index ?? null, 0);
      a.Key_buffer?.fill(0); b.Key_buffer?.fill(0);
      if (b.status !== this.km4Status("SUCCESSFUL")) { lastFail = b; break; }
      okN += 1; if (first < 0) first = a.index ?? -1; last = a.index ?? -1;
    }
    const bits = (this.km.chunkBytes(this.ksid) ?? KEY_BYTES) * 8;
    this.ok += okN; this.failed += n - okN;
    if (okN > 0) {
      this.lastStatus = this.km4Status("SUCCESSFUL");
      this.log("004", `GET_KEY x${okN} on both sides, index ${first}..${last}, Key_chunk_size ${bits / 8} bytes, metadata hops ${this.route?.relays ?? 0}`, this.lastStatus, "T11");
    }
    if (lastFail) {
      this.lastStatus = lastFail.status;
      this.log("004", `GET_KEY x${n - okN} failed: ${lastFail.detail ?? statusById(lastFail.status ?? 0).paraphrase}`, lastFail.status, lastFail.transition);
    }
    return { delivered: okN * bits, unmet: (n - okN) * bits };
  }

  // ---- routing ----------------------------------------------------------------
  private graph(): RouteGraph {
    return {
      nodes: this.preset.nodes.map((n) => n.id),
      links: this.links.filter((l) => l.kind === "qkd" && !l.notInRun).map((l) => ({ id: l.id, a: l.a, b: l.b })),
    };
  }

  private view(needBits: number): (id: string) => LinkView {
    return (id) => {
      const l = this.links.find((x) => x.id === id)!;
      if (l.down) return { up: false, usable: false, why: l.downReason ?? "down", availableBits: null, rateBps: l.genBps };
      if (this.accounting === "route-only") {
        return { up: true, usable: true, availableBits: null, rateBps: l.genBps };
      }
      if (this.accounting === "stores") {
        if (l.storedBits === null || l.thresholdBits === null) {
          return { up: true, usable: false, why: "no store in the cited run", availableBits: null, rateBps: l.genBps };
        }
        const avail = l.storedBits - l.thresholdBits;
        return avail >= needBits
          ? { up: true, usable: true, availableBits: avail, rateBps: l.genBps }
          : { up: true, usable: false, why: "store at its minimum threshold", availableBits: avail, rateBps: l.genBps };
      }
      if (this.accounting === "service-buffer") {
        // Stores not stated: usable while up and the reported average rate
        // covers the transfer within one tick.
        if (l.genBps === null) return { up: true, usable: false, why: "no reported rate", availableBits: null, rateBps: null };
        const cap = l.genBps * this.tickS;
        return cap >= needBits
          ? { up: true, usable: true, availableBits: null, rateBps: l.genBps }
          : { up: true, usable: false, why: "reported rate cannot cover the refill in one tick", availableBits: null, rateBps: l.genBps };
      }
      // keys: a link that can generate is a candidate even while its buffer
      // is momentarily empty -- that is "waiting for key", not a failed link,
      // and treating it as a failure made the route flap every tick on slow
      // links. refillStream() relays only when the bottleneck holds a key.
      const keys = l.storedKeys ?? 0;
      if (l.genBps === null && keys === 0) {
        return { up: true, usable: false, why: "no reported rate", availableBits: 0, rateBps: null };
      }
      return { up: true, usable: true, availableBits: keys * KEY_BITS, rateBps: l.genBps };
    };
  }

  private chooseRoute(needBits = KEY_BITS) {
    const prev = this.route;
    const sel = selectRoute(this.graph(), this.demandFrom, this.demandTo, this.view(needBits), {
      downNodes: this.downNodes, preferred: this.scenario?.preferredRoute?.nodes,
    });
    // Sticky among routes of equal length: keep the current route while it
    // can still carry the request, so draining buffers do not make equal-hop
    // routes alternate tick by tick. A route with FEWER hops, or the
    // scenario's preferred route, still wins at once -- that is the switch
    // back after a repair.
    let chosen = sel.chosen;
    if (prev && chosen) {
      const still = sel.ranked.find((r) => routeKey(r.nodes) === routeKey(prev.nodes));
      const preferred = this.scenario?.preferredRoute
        && routeKey(chosen.nodes) === routeKey(this.scenario.preferredRoute.nodes);
      if (still && chosen.hops >= still.hops && !preferred) chosen = still;
    }
    this.route = chosen;
    this.routeNone = sel.none ?? null;
    this.alternatives = sel.ranked;
    this.rejected = sel.rejected;
    const t = this.tickN * this.tickS;
    const was = prev ? routeKey(prev.nodes) : null;
    const now = this.route ? routeKey(this.route.nodes) : null;
    if (this.reroutes.length === 0 && now !== null) {
      this.reroutes.push({ t_s: t, from: null, to: this.route!.nodes, reason: "start" });
      return;
    }
    if (was === now) return;
    let reason: Reroute["reason"];
    if (now === null) reason = "no-route";
    else if (prev === null) reason = "recovered";
    else {
      const broken = prev.linkIds.map((id) => this.links.find((l) => l.id === id)!).find((l) => l.down);
      if (broken) reason = reasonFor(broken);
      else if (this.route!.hops < prev.hops
               || this.scenario?.preferredRoute && now === routeKey(this.scenario.preferredRoute.nodes)) reason = "recovered";
      else reason = "threshold";
    }
    this.reroutes.push({ t_s: t, from: prev?.nodes ?? null, to: this.route?.nodes ?? null, reason });
    if (this.reroutes.length > HISTORY_LIMIT) this.reroutes.shift();
  }

  // ---- relay sample -----------------------------------------------------------
  /**
   * Relay one key across the route with real one-time pads: node i sends
   * key XOR pad_i over hop i, node i+1 removes pad_i and re-pads for the next
   * hop. Returns the key; only 16-hex-character prefixes are kept in state.
   */
  private relaySample(): Uint8Array {
    const key = randomBytes(KEY_BYTES);
    const hops = this.route?.hops ?? 0;
    const pads = Array.from({ length: hops }, () => randomBytes(KEY_BYTES));
    let carried = key.slice();
    for (const pad of pads) {
      const onWire = carried.map((b, i) => b ^ pad[i]);
      carried = onWire.map((b, i) => b ^ pad[i]);
      onWire.fill(0);
    }
    const equal = carried.every((b, i) => b === key[i]);
    this.lastRelay = {
      hops,
      key_prefix: toHex(key).slice(0, PREFIX_HEX),
      pad_prefixes: pads.map((p) => toHex(p).slice(0, PREFIX_HEX)),
      recovered_equals_sent: equal,
    };
    for (const p of pads) p.fill(0);
    carried.fill(0);
    return key;
  }

  private clearKeyMaterial() {
    this.lastRelay = null;
    this.km?.clear();
  }

  // ---- timeline ---------------------------------------------------------------
  private km4Status(id: StatusId): number {
    return statusCode(id);
  }

  private log(lane: "014" | "004", text: string, status?: number | null, transition?: string) {
    this.messages.push({ t_s: this.tickN * this.tickS, lane, text, status, transition });
    if (this.messages.length > MESSAGE_LIMIT) this.messages.shift();
  }

  private log004(call: string, r: CallResult) {
    this.messages.push({ t_s: this.tickN * this.tickS, lane: "004",
      text: `${call}: ${r.http ? `HTTP ${r.http}` : `status ${r.status}`}${r.detail ? ` (${r.detail})` : ""}`,
      status: r.status, http: r.http, transition: r.transition });
    if (this.messages.length > MESSAGE_LIMIT) this.messages.shift();
  }

  // ---- loop ---------------------------------------------------------------
  private emit() { this.onState(this.snapshot()); }

  private ensureLoop() {
    if (this.timer !== null) return;
    this.lastAdvance = performance.now();
    this.timer = window.setInterval(() => this.onTimer(), 100);
  }

  private stopLoop() {
    if (this.timer !== null) { clearInterval(this.timer); this.timer = null; }
  }

  private onTimer() {
    if (this.status !== "running") return;
    if (performance.now() - this.lastAdvance < NOMINAL_TICK_DWELL_MS) return;
    this.lastAdvance = performance.now();
    this.advance();
    this.emit();
  }
}

