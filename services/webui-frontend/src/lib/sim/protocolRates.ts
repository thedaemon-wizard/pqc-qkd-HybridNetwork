/**
 * Asymptotic secret-key rates for three QKD families, for the curves on
 * /qkd-protocols. A teaching model in the browser: nothing here feeds the running
 * stack, which has no MDI-QKD or BBM92 backend, and no key comes from it.
 *
 * All three are in the asymptotic limit, with infinitely many decoy states where
 * there are decoys, and with the basis factor q = 1 (the efficient-BB84 limit).
 * docs/keyrate.md section 9 derives each formula and says what is left out.
 * tools/protocol_rates.py is the reference; both reproduce
 * protocolRatesGolden.json.
 */
import { H2, gainQmu, qberEmu } from "./keyrate";

/**
 * The parameter set behind Lo, Curty and Qi (2012), Fig. 2: 0.2 dB/km, 14.5 %
 * efficiency, 1.5 % misalignment, f = 1.16. Ma and Razavi (2012), Table I give
 * the background per detector, half the 6.02e-6 of the two-detector experiment
 * the figures are taken from.
 */
export const PUBLISHED_RATE_PARAMS = Object.freeze({
  alphaDbPerKm: 0.2, etaD: 0.145, pd: 3.0e-6, eD: 0.015, f: 1.16,
});

export interface RateParams {
  alphaDbPerKm: number;
  etaD: number;
  /** Background count probability per detector and per pulse. */
  pd: number;
  eD: number;
  f: number;
}

export type RateProtocol = "bb84" | "bbm92" | "mdi";

/** Modified Bessel function I0, by its power series. */
export function besselI0(x: number): number {
  let term = 1;
  let total = 1;
  for (let k = 1; ; k++) {
    term *= (x * x / 4) / (k * k);
    total += term;
    if (term < 1e-17 * total) return total;
  }
}

export const fibreTransmittance = (alphaDbPerKm: number, lengthKm: number): number =>
  Math.pow(10, (-alphaDbPerKm * lengthKm) / 10);

// ---- MDI-QKD: Ma and Razavi (2012), Appendixes A and B -----------------------
/** Y11, Eq. (A9): the yield when both senders emit one photon. */
export function mdiY11(etaA: number, etaB: number, pd: number): number {
  return (1 - pd) ** 2 * (
    (etaA * etaB) / 2 + (2 * etaA + 2 * etaB - 3 * etaA * etaB) * pd
    + 4 * (1 - etaA) * (1 - etaB) * pd * pd
  );
}

/** e11, Eq. (A11): the single-photon error rate, which bounds the phase error. */
export function mdiE11(etaA: number, etaB: number, pd: number, eD: number): number {
  const y11 = mdiY11(etaA, etaB, pd);
  if (y11 <= 0) return 0.5;
  return (0.5 * y11 - (0.5 - eD) * (1 - pd) ** 2 * (etaA * etaB) / 2) / y11;
}

/** Q_rect and E_rect, Eqs. (B28)-(B31): the overall gain and error in the key basis. */
export function mdiGainRect(etaA: number, etaB: number, muA: number, muB: number, pd: number, eD: number): { q: number; e: number } {
  const muPrime = etaA * muA + etaB * muB;
  const x = Math.sqrt(etaA * muA * etaB * muB) / 2;
  const qC = 2 * (1 - pd) ** 2 * Math.exp(-muPrime / 2)
    * (1 - (1 - pd) * Math.exp((-etaA * muA) / 2))
    * (1 - (1 - pd) * Math.exp((-etaB * muB) / 2));
  const qE = 2 * pd * (1 - pd) ** 2 * Math.exp(-muPrime / 2)
    * (besselI0(2 * x) - (1 - pd) * Math.exp(-muPrime / 2));
  const q = qC + qE;
  return { q, e: q > 0 ? (eD * qC + (1 - eD) * qE) / q : 0.5 };
}

/** Eq. (B27). Negative where no key survives; the callers clip that to zero. */
export function mdiRate(etaA: number, etaB: number, muA: number, muB: number, pd: number, eD: number, f: number): number {
  const q11 = muA * muB * Math.exp(-muA - muB) * mdiY11(etaA, etaB, pd);
  const { q, e } = mdiGainRect(etaA, etaB, muA, muB, pd, eD);
  return q11 * (1 - H2(mdiE11(etaA, etaB, pd, eD))) - q * f * H2(e);
}

// ---- BBM92 from a thermal PDC source: Ma, Fung and Lo (2007), Eqs. (9)-(12) ---
export function bbm92GainQber(etaA: number, etaB: number, lambda: number, y0: number, eD: number): { q: number; e: number } {
  const a = 1 + etaA * lambda;
  const b = 1 + etaB * lambda;
  const c = 1 + etaA * lambda + etaB * lambda - etaA * etaB * lambda;
  const q = 1 - (1 - y0) / (a * a) - (1 - y0) / (b * b) + ((1 - y0) * (1 - y0)) / (c * c);
  if (q <= 0) return { q: 0, e: 0.5 };
  return { q, e: (0.5 * q - (2 * (0.5 - eD) * etaA * etaB * lambda * (1 + lambda)) / (a * b * c)) / q };
}

export function bbm92Rate(etaA: number, etaB: number, lambda: number, y0: number, eD: number, f: number): number {
  const { q, e } = bbm92GainQber(etaA, etaB, lambda, y0, eD);
  return q * (1 - f * H2(e) - H2(e));
}

// ---- Decoy-state BB84, infinite decoys: docs/keyrate.md sections 2, 3 and 6 ----
export function bb84Terms(eta: number, mu: number, y0: number, eD: number): { q: number; e: number; q1: number; e1: number } {
  const q = gainQmu(y0, eta, mu);
  const y1 = y0 + eta - y0 * eta;
  return {
    q, e: qberEmu(y0, eta, eD, mu),
    q1: y1 * mu * Math.exp(-mu),
    e1: y1 > 0 ? (y0 / 2 + eD * eta) / y1 : 0.5,
  };
}

export function bb84Rate(eta: number, mu: number, y0: number, eD: number, f: number): number {
  const { q, e, q1, e1 } = bb84Terms(eta, mu, y0, eD);
  return q1 * (1 - H2(e1)) - f * q * H2(e);
}

/**
 * The repeaterless bound, Pirandola et al. (2017), Eq. (19): bits per channel
 * use over a pure-loss channel of transmittance `eta`, the fibre alone here.
 */
export function plobBound(eta: number): number {
  return eta > 0 && eta < 1 ? -Math.log2(1 - eta) : Infinity;
}

const INTENSITY_LO = 1e-4;
const INTENSITY_HI = 3;
const GRID_POINTS = 61;
const GOLDEN_STEPS = 48;
const GOLDEN_RATIO = (Math.sqrt(5) - 1) / 2;

/** The best value of `fn` on [lo, hi]: a log grid, then a golden section around its best. */
export function bestOver(fn: (x: number) => number, lo = INTENSITY_LO, hi = INTENSITY_HI): { value: number; at: number } {
  const ratio = Math.pow(hi / lo, 1 / (GRID_POINTS - 1));
  let bestI = 0;
  let bestV = -Infinity;
  for (let i = 0; i < GRID_POINTS; i++) {
    const v = fn(lo * ratio ** i);
    if (v > bestV) { bestV = v; bestI = i; }
  }
  let a = lo * ratio ** Math.max(0, bestI - 1);
  let b = lo * ratio ** Math.min(GRID_POINTS - 1, bestI + 1);
  let c = b - GOLDEN_RATIO * (b - a);
  let d = a + GOLDEN_RATIO * (b - a);
  let fc = fn(c);
  let fd = fn(d);
  for (let k = 0; k < GOLDEN_STEPS; k++) {
    if (fc > fd) {
      b = d; d = c; fd = fc;
      c = b - GOLDEN_RATIO * (b - a);
      fc = fn(c);
    } else {
      a = c; c = d; fc = fd;
      d = a + GOLDEN_RATIO * (b - a);
      fd = fn(d);
    }
  }
  const at = fc > fd ? c : d;
  const value = Math.max(fc, fd);
  return value >= bestV ? { value, at } : { value: bestV, at: lo * ratio ** bestI };
}

/** Two detectors at one end: the probability that at least one fires in the dark. */
export const backgroundPerSide = (pd: number): number => 1 - (1 - pd) * (1 - pd);

/**
 * The rate at this length with the intensity chosen for it, zero when no key
 * survives. `relayShare` is the share of the fibre on Alice's side of the relay
 * or source. MDI's second intensity is set so both pulses reach the relay equally
 * bright, which minimises the intrinsic error (Ma and Razavi, after Eq. (B14)),
 * and is not a joint optimum of the two when the arms differ.
 */
export function ratePoint(protocol: RateProtocol, lengthKm: number, p: RateParams, relayShare = 0.5): { rate: number; intensity: number | null } {
  let fn: (x: number) => number;
  if (protocol === "bb84") {
    const eta = p.etaD * fibreTransmittance(p.alphaDbPerKm, lengthKm);
    const y0 = backgroundPerSide(p.pd);
    fn = (mu) => bb84Rate(eta, mu, y0, p.eD, p.f);
  } else {
    const etaA = p.etaD * fibreTransmittance(p.alphaDbPerKm, lengthKm * relayShare);
    const etaB = p.etaD * fibreTransmittance(p.alphaDbPerKm, lengthKm * (1 - relayShare));
    if (protocol === "bbm92") {
      const y0 = backgroundPerSide(p.pd);
      fn = (lambda) => bbm92Rate(etaA, etaB, lambda, y0, p.eD, p.f);
    } else {
      const balance = etaA / etaB;
      fn = (mu) => mdiRate(etaA, etaB, mu, mu * balance, p.pd, p.eD, p.f);
    }
  }
  const { value, at } = bestOver(fn);
  return value > 0 ? { rate: value, intensity: at } : { rate: 0, intensity: null };
}

/** The longest fibre that still gives key, to 0.1 km. */
export function maxDistanceKm(protocol: RateProtocol, p: RateParams, relayShare = 0.5, topKm = 1000): number {
  if (ratePoint(protocol, 0, p, relayShare).rate <= 0) return 0;
  let lo = 0;
  let hi = topKm;
  if (ratePoint(protocol, hi, p, relayShare).rate > 0) return hi;
  while (hi - lo > 0.1) {
    const mid = (lo + hi) / 2;
    if (ratePoint(protocol, mid, p, relayShare).rate > 0) lo = mid;
    else hi = mid;
  }
  return Math.round(lo * 10) / 10;
}
