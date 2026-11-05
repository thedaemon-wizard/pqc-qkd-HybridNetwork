import { useEffect, useMemo, useRef, useState } from "react";
import Plot from "react-plotly.js";
import Button from "../components/Button";
import ExportToolbar from "../components/ExportToolbar";
import KPI from "../components/KPI";
import PageHeader from "../components/PageHeader";
import Panel from "../components/Panel";
import QkdRoundSvg, { ROUND_VIEW } from "../components/QkdRoundSvg";
import { PART_EDGES } from "../components/RunStatusStrip";
import ScrollRegion from "../components/ScrollRegion";
import { colors } from "../lib/commonStyles";
import { narrowColumns, useNarrowLayout, usePrefersReducedMotion } from "../lib/layout";
import { PLOT_CONFIG } from "../lib/plotConfig";
import {
  PUBLISHED_RATE_PARAMS, fibreTransmittance, maxDistanceKm, plobBound, ratePoint,
  type RateParams, type RateProtocol,
} from "../lib/sim/protocolRates";
import {
  PROTOCOL_NAMES, ROUND_PARTS, partAt, photonPositions, playRound, seededDraw, stateLabel,
  type Round, type RoundProtocol,
} from "../lib/sim/qkdRounds";
import { seedFromLocation } from "../lib/sim/runSeed";

/**
 * QKD Protocols: one idealised round of BB84, BBM92 or MDI-QKD at a time, the
 * asymptotic key-rate curves of the same three, and the families compared with
 * the conditions of each result.
 *
 * Everything here is computed in the browser, and the page makes no request of its
 * own (exports excepted, as on every page). The banner says what it is before
 * anything runs. docs/keyrate.md section 9 derives the curves.
 */

const SPEEDS = [
  { id: "slow", label: "Slow (4.8 s per round)", ms: 4800 },
  { id: "normal", label: "Normal (2.4 s per round)", ms: 2400 },
  { id: "fast", label: "Fast (0.9 s per round)", ms: 900 },
] as const;
const DEFAULT_SPEED_MS = 2400;
/** Of a round's time, the part played; the rest shows its outcome. */
const PLAY_SHARE = 0.85;
/** Rounds kept in the table. No total is kept: this is not a key generator. */
const ROUNDS_SHOWN = 10;
const CURVE_MAX_KM = 400;
const CURVE_STEP_KM = 5;
/** The table's width below the shell's breakpoint; its own box scrolls past that. */
const NARROW_ROUNDS_TABLE_MIN_PX = 560;
const NARROW_FAMILIES_TABLE_MIN_PX = 800;

const CURVE_NAMES: Record<RateProtocol, string> = {
  bb84: "BB84, decoy states",
  bbm92: "BBM92, thermal PDC source",
  mdi: "MDI-QKD, decoy states",
};
const CURVE_COLOURS: Record<RateProtocol, string> = {
  bb84: colors.accent, bbm92: colors.qkd, mdi: colors.success,
};
const RATE_PROTOCOLS: RateProtocol[] = ["bb84", "bbm92", "mdi"];

const FIELDS: { key: keyof RateParams; label: string; step: number }[] = [
  { key: "alphaDbPerKm", label: "Fibre loss (dB/km)", step: 0.01 },
  { key: "etaD", label: "Detector efficiency", step: 0.005 },
  { key: "pd", label: "Background per detector, per pulse", step: 1e-6 },
  { key: "eD", label: "Misalignment error", step: 0.001 },
  { key: "f", label: "Error-correction inefficiency", step: 0.01 },
];

/** Each result with its conditions. Selected, and not a ranking. */
const FAMILIES: { name: string; trust: string; scaling: string; results: { text: string; ref: string; url: string }[] }[] = [
  {
    name: "Prepare and measure: BB84 with decoy states",
    trust: "The source and the detectors are characterised and trusted. Decoy states bound the single-photon contribution of weak coherent pulses.",
    scaling: "About the channel transmittance, with decoy states",
    results: [
      { text: "421.1 km of ultralow-loss fibre, 71.9 dB: 0.25 bit/s, finite key at 1e-9, a three-state one-decoy protocol at 2.5 GHz", ref: "Boaron et al., PRL 121, 190502 (2018)", url: "https://arxiv.org/abs/1807.03222" },
      { text: "10 km of standard fibre: 115.8 Mbit/s (read from the abstract)", ref: "Li et al., Nat. Photon. 17, 416 (2023)", url: "https://doi.org/10.1038/s41566-023-01166-4" },
    ],
  },
  {
    name: "Entanglement-based: E91, BBM92",
    trust: "The source may sit between the users and need not be trusted. BBM92 uses two bases and no Bell test, and is equivalent to BB84; E91 adds a CHSH test. The detectors are still trusted.",
    scaling: "About the channel transmittance, with the source in the middle (Ma, Fung and Lo, 2007)",
    results: [
      { text: "This site's Thuringia network on /protocol-lab restates a BBM92 chain's published rates", ref: "arXiv:2608.18869", url: "https://arxiv.org/abs/2608.18869" },
    ],
  },
  {
    name: "Measurement-device-independent: MDI-QKD",
    trust: "The measurement unit may be a black box. This targets attacks on the detectors only: the sources must still be trusted and characterised, and the labs shielded.",
    scaling: "The product of the two arms' transmittances, so linear in the whole channel. It does not beat the repeaterless bound",
    results: [
      { text: "404 km of ultralow-loss fibre: 3.2e-4 bit/s, 2,584 bits in three months, finite key", ref: "Yin et al., PRL 117, 190501 (2016)", url: "https://arxiv.org/abs/1606.06821" },
      { text: "442 km of ultralow-loss fibre: positive key (read from the abstract)", ref: "PRA 108, 022605 (2023)", url: "https://doi.org/10.1103/PhysRevA.108.022605" },
      { text: "30 km of deployed fibre in Hefei, 9.2 dB: 16.9 bit/s over 18.2 h, finite key", ref: "Tang et al., IEEE JSTQE 21(3) (2015)", url: "https://arxiv.org/abs/1408.2330" },
      { text: "Asynchronous MDI, 508.16 km of ultralow-loss fibre on spools: 42.64 bit/s, finite key", ref: "Zhou et al., PRL 130, 250801 (2023)", url: "https://arxiv.org/abs/2212.14190" },
    ],
  },
  {
    name: "Twin-field",
    trust: "An untrusted relay, single-photon interference and phase-coherent fields. The 2018 rate equation did not cover general attacks; later analyses do.",
    scaling: "About the square root of the transmittance. It is not point-to-point, so the repeaterless bound does not apply to it as it stands",
    results: [
      { text: "1002 km of ultralow-loss fibre on spools, 156.5 dB: 0.0034 bit/s, asymptotic", ref: "Liu et al., PRL 130, 210801 (2023)", url: "https://arxiv.org/abs/2303.15795" },
      { text: "The same fibre: 0.0011 bit/s, finite and composable", ref: "Quantum Front. 2, 16", url: "https://arxiv.org/abs/2402.00005" },
      { text: "253.9 km of deployed fibre, Frankfurt to Kehl, 56.0 dB: 110.1 bit/s over 7.5 h, finite key", ref: "Pittaluga et al., Nature 640, 911 (2025)", url: "https://doi.org/10.1038/s41586-025-08801-w" },
    ],
  },
  {
    name: "Continuous-variable: GG02",
    trust: "Gaussian-modulated coherent states, with Bob measuring one quadrature. The paper's analysis covers individual attacks, at line transmission above 50 %.",
    scaling: "Not modelled on this page; the KME has its own cvqkd backend",
    results: [
      { text: "The protocol's own analysis", ref: "Grosshans and Grangier, PRL 88, 057902 (2002)", url: "https://doi.org/10.1103/PhysRevLett.88.057902" },
    ],
  },
  {
    name: "Device-independent",
    trust: "The key rate comes from a Bell (CHSH) violation. Quantum theory, isolation of the labs, private inputs and trusted classical processing are still assumed.",
    scaling: "Not modelled on this page",
    results: [
      { text: "Trapped ions about 2 m apart, in one room: 95,884 bits extracted, finite key at 1e-10, general attacks", ref: "Nadlinger et al., Nature 607, 682 (2022)", url: "https://arxiv.org/abs/2109.14600" },
      { text: "Atoms 400 m apart, 700 m of fibre: 0.07 bit per event, asymptotic", ref: "Zhang et al., Nature 607, 687 (2022)", url: "https://arxiv.org/abs/2110.00575" },
      { text: "11 km on spools, all nodes in one lab, locality loophole open: an estimated 0.112 bit per event, finite key at 1e-5; 100 km is asymptotic only", ref: "Science 391, 592 (2026)", url: "https://arxiv.org/abs/2602.09596" },
    ],
  },
];

const drawOf = (seed: number | null): (() => number) => (seed === null ? Math.random : seededDraw(seed));

export default function QkdProtocols() {
  const narrow = useNarrowLayout();
  const reduced = usePrefersReducedMotion();
  const [protocol, setProtocol] = useState<RoundProtocol>("mdi");
  const [speedMs, setSpeedMs] = useState<number>(DEFAULT_SPEED_MS);
  const [running, setRunning] = useState(false);
  const [round, setRound] = useState<Round | null>(null);
  const [rounds, setRounds] = useState<{ n: number; r: Round }[]>([]);
  const [partIndex, setPartIndex] = useState<number | null>(null);
  const [params, setParams] = useState<RateParams>({ ...PUBLISHED_RATE_PARAMS });
  const [relayShare, setRelayShare] = useState(0.5);

  const seed = useMemo(() => seedFromLocation(), []);
  const draw = useRef(drawOf(seed));
  const counter = useRef(0);
  const photon0 = useRef<SVGCircleElement>(null);
  const photon1 = useRef<SVGCircleElement>(null);
  const frame = useRef(0);
  const nextRound = useRef(0);

  const hidePhotons = () => {
    photon0.current?.setAttribute("visibility", "hidden");
    photon1.current?.setAttribute("visibility", "hidden");
  };
  const stopPlay = () => {
    cancelAnimationFrame(frame.current);
    window.clearTimeout(nextRound.current);
    hidePhotons();
    setPartIndex(null);
  };
  const sendRound = () => {
    const r = playRound(protocol, draw.current);
    counter.current += 1;
    const n = counter.current;
    setRound(r);
    setRounds((old) => [{ n, r }, ...old].slice(0, ROUNDS_SHOWN));
  };

  // Each new round plays once. With reduced motion asked for no frame loop runs,
  // and the outcome shows at once.
  useEffect(() => {
    if (!round) return undefined;
    cancelAnimationFrame(frame.current);
    window.clearTimeout(nextRound.current);
    const finish = () => {
      hidePhotons();
      setPartIndex(null);
      if (running) nextRound.current = window.setTimeout(sendRound, reduced ? speedMs : speedMs * (1 - PLAY_SHARE));
    };
    if (reduced) { finish(); return () => window.clearTimeout(nextRound.current); }
    const playMs = speedMs * PLAY_SHARE;
    const started = performance.now();
    const refs = [photon0.current, photon1.current];
    const { LEFT, RIGHT } = ROUND_VIEW;
    const step = (t: number) => {
      const p = Math.min(1, (t - started) / playMs);
      if (p >= 1) { finish(); return; }
      setPartIndex(partAt(round.protocol, p));
      const at = photonPositions(round.protocol, p);
      refs.forEach((c, i) => {
        if (!c) return;
        if (at[i] === undefined) { c.setAttribute("visibility", "hidden"); return; }
        c.setAttribute("cx", (LEFT + (RIGHT - LEFT) * at[i]).toFixed(1));
        c.setAttribute("visibility", "visible");
      });
      frame.current = requestAnimationFrame(step);
    };
    frame.current = requestAnimationFrame(step);
    return () => { cancelAnimationFrame(frame.current); window.clearTimeout(nextRound.current); };
    // A new round object restarts the play; the rest is read when it starts.
  }, [round, reduced]); // eslint-disable-line react-hooks/exhaustive-deps

  function run() { setRunning(true); sendRound(); }
  function pause() { setRunning(false); stopPlay(); }
  function step() { setRunning(false); sendRound(); }
  function reset() {
    setRunning(false);
    stopPlay();
    setRound(null);
    setRounds([]);
    counter.current = 0;
    draw.current = drawOf(seed);
  }
  function pickProtocol(p: RoundProtocol) {
    reset();
    setProtocol(p);
  }

  const lengths = useMemo(() => Array.from({ length: CURVE_MAX_KM / CURVE_STEP_KM + 1 }, (_, i) => i * CURVE_STEP_KM), []);
  const curves = useMemo(() => Object.fromEntries(RATE_PROTOCOLS.map((name) => [
    name, lengths.map((l) => ratePoint(name, l, params, relayShare)),
  ])) as Record<RateProtocol, { rate: number; intensity: number | null }[]>, [lengths, params, relayShare]);
  const reach = useMemo(() => Object.fromEntries(RATE_PROTOCOLS.map((name) => [
    name, maxDistanceKm(name, params, relayShare),
  ])) as Record<RateProtocol, number>, [params, relayShare]);

  function csvRows() {
    return lengths.map((l, i) => ({
      length_km: l,
      plob_bound_bits_per_use: l === 0 ? "" : plobBound(fibreTransmittance(params.alphaDbPerKm, l)),
      ...Object.fromEntries(RATE_PROTOCOLS.flatMap((name) => [
        [`${name}_rate_bits_per_pulse`, curves[name][i].rate],
        [`${name}_intensity`, curves[name][i].intensity ?? ""],
      ])),
      relay_share: relayShare,
      ...params,
    }));
  }
  function runLog(): string {
    const head = [
      "# QKD Protocols: idealised rounds and asymptotic key rates (model; nothing here is measured)",
      `# generated: ${new Date().toISOString()}`,
      `# protocol:  ${PROTOCOL_NAMES[protocol]}`,
      `# seed:      ${seed === null ? "unpinned" : seed}`,
      `# rates at:  ${JSON.stringify(params)}, relay share ${relayShare}`,
      `# longest fibre with key in this model, km: ${JSON.stringify(reach)}`,
      "",
    ];
    const body = [...rounds].reverse().map(({ n, r }) =>
      `round ${n}: Alice ${r.alice.basis}${r.alice.bit} Bob ${r.bob.basis}${r.bob.bit}${r.relay ? ` relay ${r.relay}` : ""} `
      + `${r.kept ? `kept, bit ${r.key}` : "discarded"} (${r.why})`);
    return [...head, ...body, ""].join("\n");
  }

  const parts = ROUND_PARTS[protocol];
  const cell = { padding: "3px 8px", borderBottom: `1px solid ${colors.border}`, verticalAlign: "top" as const };
  const head = { ...cell, textAlign: "left" as const, color: colors.textPri };

  return (
    <div>
      <PageHeader
        title="QKD Protocols (idealised rounds and asymptotic key rates)"
        subtitle={<>One round of BB84, BBM92 or MDI-QKD at a time, the asymptotic key-rate curves of the
          same three, and the families compared with the conditions of each result. The link-by-link
          simulation is on <code>/protocol-lab</code>, and the finite-key BB84 model on <code>/physics</code>.</>}
      />

      <div role="note" style={{ border: `1px solid ${colors.warn}`, background: colors.panelDark,
                                 color: colors.textPri, borderRadius: 8, padding: "10px 12px",
                                 fontSize: 13, marginBottom: 12, lineHeight: 1.5 }}>
        <b>Model, not measurement.</b> Everything here is computed in your browser. The rounds are
        idealised, with no loss, noise or eavesdropper. The curves are the cited papers' asymptotic
        formulas at the parameters shown: not measured, not a finite-key bound, and not a prediction
        for any product. The running stack has no MDI-QKD or BBM92 backend, and no key from these
        models reaches it.
      </div>

      <div style={{ marginBottom: 12 }}>
        <ExportToolbar
          name="qkd-protocols"
          hasRunControl
          logProvider={runLog}
          pngTargetSelector="#qkd-round-svg"
          jsonProvider={() => ({ params, relay_share: relayShare, reach_km: reach, protocol, seed, rounds: rounds.map(({ n, r }) => ({ n, ...r })) })}
          csvProvider={csvRows}
        />
      </div>

      <Panel title="One round at a time" style={{ marginBottom: 12 }}>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center", marginBottom: 8 }}>
          <label style={{ fontSize: 12, color: colors.textSec }}>Protocol{" "}
            <select aria-label="Protocol" value={protocol} onChange={(e) => pickProtocol(e.target.value as RoundProtocol)}>
              {(Object.keys(PROTOCOL_NAMES) as RoundProtocol[]).map((p) => <option key={p} value={p}>{PROTOCOL_NAMES[p]}</option>)}
            </select>
          </label>
          <Button onClick={run} disabled={running}>▶ Run</Button>
          <Button variant="secondary" onClick={pause} disabled={!running}>⏸ Pause</Button>
          <Button variant="secondary" onClick={step} disabled={running}>⏭ Step</Button>
          <Button variant="ghost" onClick={reset}>⏹ Reset</Button>
          <label style={{ fontSize: 12, color: colors.textSec }}>Speed{" "}
            <select aria-label="Round speed" value={speedMs} onChange={(e) => setSpeedMs(Number(e.target.value))}>
              {SPEEDS.map((s) => <option key={s.id} value={s.ms}>{s.label}</option>)}
            </select>
          </label>
        </div>
        <div style={{ maxWidth: 780, margin: "0 auto" }}>
          <QkdRoundSvg protocol={protocol} round={round} partIndex={partIndex}
                       photonRefs={[photon0, photon1]} compact={narrow} />
        </div>
        <ol style={{ listStyle: "none", margin: "8px 0 0 0", padding: 0, display: "grid", gap: 6,
                     gridTemplateColumns: "repeat(auto-fit, minmax(120px, 1fr))" }}>
          {parts.map((label, i) => {
            const lit = partIndex === i;
            const reached = round !== null && (partIndex === null || i <= partIndex);
            return (
              <li key={label} aria-current={lit ? "step" : undefined}
                  style={{ fontSize: 11, padding: "4px 6px", borderRadius: 4, minWidth: 0,
                           ...PART_EDGES(lit ? colors.accent : colors.border),
                           borderLeft: `4px solid ${reached ? colors.success : colors.border}`,
                           background: lit ? colors.active : "transparent",
                           color: reached ? colors.textPri : colors.textMute,
                           transition: "background 0.12s, border-color 0.12s" }}>
                {i + 1}. {label}
              </li>
            );
          })}
        </ol>
        {protocol === "mdi" && (
          <div style={{ fontSize: 12, color: colors.textSec, marginTop: 8, lineHeight: 1.5 }}>
            With linear optics the relay can identify only two of the four Bell states, so it reports
            <b> ψ−</b>, <b>ψ+</b> or no result. Equal bits in the Z basis bunch and give no result; in the
            X basis a pair gives a result half of the time. Bob flips his bit in the Z basis, and in the
            X basis only on ψ− (Lo, Curty and Qi, 2012, Table I). The relay learns the relation between
            the two bits and neither bit.
          </div>
        )}
        <ScrollRegion aria-label="Latest rounds table" style={{ marginTop: 8 }}>
          <table style={{ borderCollapse: "collapse", fontSize: 12, color: colors.textSec, width: "100%",
                          minWidth: narrow ? NARROW_ROUNDS_TABLE_MIN_PX : undefined }}>
            <thead>
              <tr>
                {["Round", "Alice", "Bob", ...(protocol === "mdi" ? ["Relay", "Bob flips"] : []), "Outcome"].map((h) =>
                  <th key={h} style={head}>{h}</th>)}
              </tr>
            </thead>
            <tbody>
              {rounds.length === 0 ? (
                <tr><td style={cell} colSpan={protocol === "mdi" ? 6 : 4}>Press Run or Step to send a round.</td></tr>
              ) : rounds.map(({ n, r }) => (
                <tr key={n}>
                  <td style={cell}>{n}</td>
                  <td style={cell}>{r.alice.basis}, {r.alice.bit} = {stateLabel(r.alice.basis, r.alice.bit)}</td>
                  <td style={cell}>{r.bob.basis}, {r.bob.bit} = {stateLabel(r.bob.basis, r.bob.bit)}</td>
                  {protocol === "mdi" && <td style={cell}>{r.relay === "none" ? "no result" : r.relay === "psi-" ? "ψ−" : "ψ+"}</td>}
                  {protocol === "mdi" && <td style={cell}>{r.kept ? (r.flip ? "yes" : "no") : "n/a"}</td>}
                  <td style={{ ...cell, color: r.kept ? colors.success : colors.textMute }}>
                    {r.kept ? `kept, bit ${r.key}` : "discarded"}: {r.why}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </ScrollRegion>
      </Panel>

      <Panel title="Key rate against fibre length (asymptotic model)" style={{ marginBottom: 12 }}>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(170px, 1fr))", gap: 8, marginBottom: 8 }}>
          {FIELDS.map((f) => (
            <label key={f.key} style={{ fontSize: 12, color: colors.textSec, display: "flex", flexDirection: "column", gap: 2 }}>
              {f.label}
              <input aria-label={f.label} type="number" min={0} step={f.step} value={params[f.key]}
                     onChange={(e) => {
                       const v = Number(e.target.value);
                       if (Number.isFinite(v) && v >= 0) setParams({ ...params, [f.key]: v });
                     }} />
            </label>
          ))}
          <label style={{ fontSize: 12, color: colors.textSec, display: "flex", flexDirection: "column", gap: 2 }}>
            Relay or source position, share of the fibre on Alice's side: {relayShare.toFixed(2)}
            <input aria-label="Relay or source position" type="range" min={0.1} max={0.9} step={0.05} value={relayShare}
                   onChange={(e) => setRelayShare(Number(e.target.value))} />
          </label>
        </div>
        <div style={{ marginBottom: 8 }}>
          <Button variant="ghost" size="sm" onClick={() => { setParams({ ...PUBLISHED_RATE_PARAMS }); setRelayShare(0.5); }}>
            Back to the published parameters
          </Button>
        </div>
        <div style={{ display: "grid", gridTemplateColumns: narrowColumns(narrow, "repeat(3, minmax(0, 1fr))"), gap: 12, marginBottom: 8 }}>
          {RATE_PROTOCOLS.map((name) => (
            <KPI key={name} label={`${CURVE_NAMES[name]}: longest fibre with key, this model (km)`} value={reach[name]} />
          ))}
        </div>
        <Plot
          data={[
            ...RATE_PROTOCOLS.map((name) => ({
              x: lengths, y: curves[name].map((c) => (c.rate > 0 ? c.rate : null)),
              type: "scatter" as const, mode: "lines" as const, name: CURVE_NAMES[name],
              line: { color: CURVE_COLOURS[name], width: 2 },
              hovertemplate: "%{x} km: %{y:.3e} bits per pulse<extra>%{fullData.name}</extra>",
            })),
            {
              x: lengths.slice(1), y: lengths.slice(1).map((l) => plobBound(fibreTransmittance(params.alphaDbPerKm, l))),
              type: "scatter" as const, mode: "lines" as const, name: "Repeaterless bound, fibre only",
              line: { color: colors.textMute, width: 2, dash: "dash" as const },
              hovertemplate: "%{x} km: %{y:.3e} bits per channel use<extra>%{fullData.name}</extra>",
            },
          ]}
          layout={{
            autosize: true, height: narrow ? 320 : 420, margin: { l: 70, r: 20, t: 16, b: 50 },
            paper_bgcolor: "rgba(0,0,0,0)", plot_bgcolor: "rgba(0,0,0,0)", font: { color: colors.textSec, size: 12 },
            xaxis: { title: { text: "Fibre length (km)" }, gridcolor: colors.border, range: [0, CURVE_MAX_KM] },
            yaxis: { title: { text: "Secret-key rate (bits per pulse)" }, type: "log", gridcolor: colors.border, range: [-10, 1], exponentformat: "e" },
            legend: { orientation: "h", y: narrow ? -0.45 : -0.2 },
          }}
          config={PLOT_CONFIG}
          style={{ width: "100%" }}
          useResizeHandler
        />
        <div style={{ fontSize: 12, color: colors.textSec, marginTop: 8, lineHeight: 1.6 }}>
          <div><b>Read these together.</b> All three are asymptotic, with infinitely many decoy states where
            there are decoys and the basis factor at 1, the limit of very biased bases. With balanced bases
            the BB84 and BBM92 curves halve, and the MDI curve quarters if only the Z basis gives key.</div>
          <div>The intensity is chosen afresh at each length. BBM92's source and MDI's relay sit at the
            position set above; MDI's second intensity is set so that both pulses arrive equally bright,
            which minimises the intrinsic error but is not a joint optimum when the arms differ.</div>
          <div>The dashed bound (Pirandola et al., 2017) is per channel use over the fibre alone, without the
            detectors, so it sits above all of these. A longer reach on this chart is a statement about
            these formulas at these parameters, not a ranking of protocols or of any product.</div>
          <div style={{ color: colors.textMute }}>
            Sources: Lo, Curty and Qi, PRL 108, 130503 (2012), for the parameters and the MDI formula; Ma and
            Razavi, PRA 86, 062319 (2012), for its closed forms; Ma, Fung and Lo, PRA 76, 012307 (2007), for
            BBM92; Lo, Ma and Chen, PRL 94, 230504 (2005), for BB84; Pirandola et al., Nat. Commun. 8, 15043
            (2017), for the bound. Derivation and checks: docs/keyrate.md, section 9.
          </div>
        </div>
      </Panel>

      <Panel title="The families compared" style={{ marginBottom: 12 }}>
        <ScrollRegion aria-label="QKD families table">
          <table style={{ borderCollapse: "collapse", fontSize: 12, color: colors.textSec, width: "100%",
                          minWidth: narrow ? NARROW_FAMILIES_TABLE_MIN_PX : undefined }}>
            <thead>
              <tr>{["Family", "What it assumes", "Rate at high loss", "Selected results, with their conditions"].map((h) =>
                <th key={h} style={head}>{h}</th>)}</tr>
            </thead>
            <tbody>
              {FAMILIES.map((f) => (
                <tr key={f.name}>
                  <td style={{ ...cell, color: colors.textPri }}>{f.name}</td>
                  <td style={cell}>{f.trust}</td>
                  <td style={cell}>{f.scaling}</td>
                  <td style={cell}>
                    <ul style={{ margin: 0, paddingLeft: 16 }}>
                      {f.results.map((r) => (
                        <li key={r.url}>{r.text} (<a href={r.url} target="_blank" rel="noreferrer" style={{ color: colors.accent }}>{r.ref}</a>)</li>
                      ))}
                    </ul>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </ScrollRegion>
        <div style={{ fontSize: 11, color: colors.textMute, marginTop: 6 }}>
          Selected on 2026-11-05 from what could be read at the source, and not a ranking: distances, keys and
          fibres differ, and a spool in a lab is not a deployed link. Check the source before repeating a number.
        </div>
      </Panel>
    </div>
  );
}
