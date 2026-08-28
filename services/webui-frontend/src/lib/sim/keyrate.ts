/**
 * Closed-form QKD key-rate — faithful TypeScript port of
 * services/bb84-kme/app/backends/_skr.py -- Lo-Ma two-decoy asymptotic bound
 * (PRL 94, 230504 (2005)) plus the Lim et al. finite-key analysis
 * (PRA 89, 022307 (2014), arXiv:1311.7129). Pure functions; the single source
 * of truth for the client-side Physics + BB84 numbers (no backend).
 *
 * tests/test_keyrate_ports_agree.py fails if this drifts from the Python.
 */

export function H2(x: number): number {
  return 0.0 < x && x < 1.0
    ? -x * Math.log2(x) - (1 - x) * Math.log2(1 - x)
    : 0.0;
}

export function totalTransmittance(
  etaD: number, alphaDbPerKm: number, lKm: number,
): number {
  return etaD * Math.pow(10, (-alphaDbPerKm * lKm) / 10.0);
}

/** Q_μ = Y0 + 1 - exp(-η·μ)  (Lo-Ma 2005 eq 32). */
export function gainQmu(Y0: number, etaTotal: number, intensity: number): number {
  return Y0 + 1.0 - Math.exp(-etaTotal * intensity);
}

/** E_μ = [Y0/2 + e_d·(1 - exp(-η·μ))] / Q_μ. */
export function qberEmu(
  Y0: number, etaTotal: number, eD: number, intensity: number,
): number {
  const q = gainQmu(Y0, etaTotal, intensity);
  if (q <= 0.0) return 0.5;
  return (Y0 / 2.0 + eD * (1.0 - Math.exp(-etaTotal * intensity))) / q;
}

/** Lo-Ma two-decoy lower bound on the asymptotic SKR (per pulse). */
export function asymptoticSkrPerPulse(p: {
  Y0: number; etaTotal: number; eD: number;
  mu: number; nu1: number; nu2: number; fEC: number;
}): number {
  const { Y0, etaTotal, eD, mu, nu1, nu2, fEC } = p;
  const Q_mu = gainQmu(Y0, etaTotal, mu);
  const E_mu = qberEmu(Y0, etaTotal, eD, mu);
  const Q_nu1 = gainQmu(Y0, etaTotal, nu1);
  const Q_nu2 = nu2 > 0 ? gainQmu(Y0, etaTotal, nu2) : Y0;
  const E_nu1 = qberEmu(Y0, etaTotal, eD, nu1);
  if (nu1 <= 0 || mu - nu1 <= 0) return 0.0;
  // Ma et al. PRA 72, 012326 (2005), Eq. (18)/(34): the GENERAL two-decoy
  // denominator. It previously read `mu * nu1 - nu1 * nu1`, that expression
  // with nu2 = 0 substituted, while the numerator kept its (nu1^2 - nu2^2)
  // term -- the two halves assumed different nu2. Validity is nu1 + nu2 < mu.
  // Ma et al. Eq. (13) is the validity condition for the Eq. (18) bound:
  //     0 <= nu2 < nu1   and   nu1 + nu2 < mu
  // `denom <= 0` is NOT equivalent: denom factorises as
  // (nu1 - nu2) * (mu - nu1 - nu2), so it is positive when BOTH margins are
  // negative. mu=0.5, nu1=0.1, nu2=0.45 gave denom=+0.0175 and a 21 % high
  // rate, reachable from the nu2 field on /physics.
  if (!(nu2 >= 0 && nu2 < nu1 && nu1 + nu2 < mu)) return 0;
  const denom = mu * nu1 - mu * nu2 - nu1 * nu1 + nu2 * nu2;
  if (denom <= 0) return 0;   // unreachable given Eq. (13); divisor guard only
  let Y1_L = (mu / denom) * (
    Q_nu1 * Math.exp(nu1) - Q_nu2 * Math.exp(nu2)
    - ((nu1 * nu1 - nu2 * nu2) / (mu * mu)) * (Q_mu * Math.exp(mu) - Y0)
  );
  Y1_L = Math.max(Y1_L, 0.0);
  if (Y1_L <= 0 || nu1 <= 0) return 0.0;
  // Ma et al. Eq. (22), the general two-decoy bound. This used Eq. (33) -- the
  // Vacuum+Weak form with nu2 = 0 -- while Y1_L above already used the general
  // nu2 form, so the two halves of one rate assumed different nu2. Optimistic
  // by +0.15 % at the optimiser's own grid point nu2 = 0.01. The forms
  // coincide exactly at nu2 = 0, so the shipped default is unchanged.
  let e1_U: number;
  if (nu2 > 0) {
    const E_nu2 = qberEmu(Y0, etaTotal, eD, nu2);
    e1_U = (E_nu1 * Q_nu1 * Math.exp(nu1) - E_nu2 * Q_nu2 * Math.exp(nu2))
           / ((nu1 - nu2) * Y1_L);
  } else {
    e1_U = (E_nu1 * Q_nu1 * Math.exp(nu1) - 0.5 * Y0) / (Y1_L * nu1);
  }
  e1_U = Math.max(0.0, Math.min(0.5, e1_U));
  const Q1 = mu * Math.exp(-mu) * Y1_L;
  const rate = 0.5 * (-Q_mu * fEC * H2(E_mu) + Q1 * (1.0 - H2(e1_U)));
  return Math.max(rate, 0.0);
}

// ===========================================================================
// Finite-key analysis: Lim, Curty, Walenta, Xu, Zbinden, PRA 89, 022307 (2014),
// arXiv:1311.7129, Eqs. (1)-(5) + supplementary Eqs. (1)-(14).
//
// This replaced `finiteKeyPenalty = sqrt(2/N) * sqrt(log2(2/eps))` subtracted
// from the asymptotic rate. That term was mis-cited to arXiv:2511.21253 (which
// contains no such expression), was 2.402x a Hoeffding deviation with log2
// where ln belongs, was channel-independent so it never entered the decoy
// inversion where the deviation is actually amplified, and was neither an
// upper nor a lower bound. Its shape gave a straight ~25 km per decade of N
// with no saturation -- at N = 1e30 it claimed key past 500 km, beyond where
// the asymptotic rate is identically zero.
//
// Conventions that are easy to get wrong, all mirrored from the Python:
//  * `hoeffdingDelta` uses NATURAL log; `samplingGamma` has ln2 in the
//    denominator and log2 inside.
//  * In Eq. (3) s0 enters with a net PLUS sign, so the LOWER bound from
//    Eq. (2) is substituted. The 1-decoy protocol needs the UPPER bound;
//    that convention here silently inflates the key.
//  * The deviation uses the TOTAL count for every intensity alike, then is
//    divided by p_k.
//  * eps_sec = 21 * eps, and the 21 pairs with the 6 in 6*log2(21/eps_sec).
// ===========================================================================

export const LIM_EPS_DIVISOR = 21.0;
export const LIM_UNION_COEFF = 6.0;

/** Lim supp. Eq. (1): delta(n, eps) = sqrt((n/2) ln(1/eps)). Natural log. */
export function hoeffdingDelta(n: number, eps: number): number {
  if (n <= 0 || !(eps > 0 && eps < 1)) return 0.0;
  return Math.sqrt(0.5 * n * Math.log(1.0 / eps));
}

/** Lim supp. Eq. (3): tau_n = sum_k p_k e^-k k^n / n!. */
export function photonNumberTau(n: number, mus: number[], ps: number[]): number {
  let fact = 1;
  for (let i = 2; i <= n; i++) fact *= i;
  let acc = 0;
  for (let i = 0; i < mus.length; i++) {
    acc += ps[i] * Math.exp(-mus[i]) * Math.pow(mus[i], n);
  }
  return acc / fact;
}

/** Lim Eq. (5) gamma -- random sampling WITHOUT replacement (Fung-Ma-Chau). */
export function samplingGamma(epsSec: number, b: number, c: number, d: number): number {
  if (c <= 0 || d <= 0 || !(b > 0 && b < 1)) return 0.5;
  const pre = ((c + d) * (1 - b) * b) / (c * d * Math.log(2.0));
  const arg = ((c + d) / (c * d * (1 - b) * b)) * Math.pow(LIM_EPS_DIVISOR / epsSec, 2);
  if (arg <= 1.0) return 0.0;
  return Math.sqrt(pre * Math.log2(arg));
}

function bracketed(nK: number, nTot: number, k: number, pK: number, dev: number) {
  const scale = Math.exp(k) / pK;
  return {
    plus: scale * Math.min(Math.max(nK + dev, 0.0), nTot),
    minus: scale * Math.min(Math.max(nK - dev, 0.0), nTot),
  };
}

function s0s1(nK: number[], mus: number[], ps: number[], eps: number,
              tau0: number, tau1: number) {
  const [mu1, mu2, mu3] = mus;
  const nTot = nK[0] + nK[1] + nK[2];
  const dev = hoeffdingDelta(nTot, eps);
  const b1 = bracketed(nK[0], nTot, mu1, ps[0], dev);
  const b2 = bracketed(nK[1], nTot, mu2, ps[1], dev);
  const b3 = bracketed(nK[2], nTot, mu3, ps[2], dev);

  let s0 = (tau0 * (mu2 * b3.minus - mu3 * b2.plus)) / (mu2 - mu3);
  s0 = Math.min(Math.max(s0, 0.0), nTot);

  const den = mu1 * (mu2 - mu3) - mu2 * mu2 + mu3 * mu3;
  if (den <= 0) return { s0, s1: 0.0, nTot };
  const s1raw = (tau1 * mu1 * (b2.minus - b3.plus
      - ((mu2 * mu2 - mu3 * mu3) / (mu1 * mu1)) * (b1.plus - s0 / tau0))) / den;
  return { s0, s1: Math.min(Math.max(s1raw, 0.0), nTot), nTot };
}

function v1(mK: number[], mus: number[], ps: number[], eps: number, tau1: number) {
  const [, mu2, mu3] = mus;
  const mTot = mK[0] + mK[1] + mK[2];
  const dev = hoeffdingDelta(mTot, eps);
  const m2p = bracketed(mK[1], mTot, mu2, ps[1], dev).plus;
  const m3m = bracketed(mK[2], mTot, mu3, ps[2], dev).minus;
  return Math.max(0.0, (tau1 * (m2p - m3m)) / (mu2 - mu3));
}

/**
 * Lim Eq. (1): the secret key LENGTH in bits.
 *
 * NOTE the counts fed in here are EXPECTED under the modelled channel, not
 * observed. Lim's theorem is conditioned on one run's data; substituting
 * expectations gives ell(E[data]), which is neither E[ell] nor a bound for any
 * particular run. This is the standard simulation convention (Lim's own Fig. 1
 * does it) but the output is an EXPECTED key length, never an achieved one.
 */
export function limKeyLength(p: {
  nXk: number[]; nZk: number[]; mXk: number[]; mZk: number[];
  mus: number[]; ps: number[]; epsSec: number; epsCor: number; fEC: number;
}) {
  const eps = p.epsSec / LIM_EPS_DIVISOR;
  const tau0 = photonNumberTau(0, p.mus, p.ps);
  const tau1 = photonNumberTau(1, p.mus, p.ps);
  const X = s0s1(p.nXk, p.mus, p.ps, eps, tau0, tau1);
  const Z = s0s1(p.nZk, p.mus, p.ps, eps, tau0, tau1);
  const vZ1 = Math.min(v1(p.mZk, p.mus, p.ps, eps, tau1), Z.s1);

  const mX = p.mXk[0] + p.mXk[1] + p.mXk[2];
  const leakEC = X.nTot > 0 ? X.nTot * p.fEC * H2(mX / X.nTot) : 0.0;

  let phiX = 0.5;
  if (Z.s1 > 0 && X.s1 > 0) {
    const b = vZ1 / Z.s1;
    phiX = Math.min(0.5, b + samplingGamma(p.epsSec, b, Z.s1, X.s1));
  }
  const penalty = LIM_UNION_COEFF * Math.log2(LIM_EPS_DIVISOR / p.epsSec)
    + Math.log2(2.0 / p.epsCor);
  const ellRaw = X.s0 + X.s1 * (1.0 - H2(phiX)) - leakEC - penalty;
  return {
    ell: Math.max(0.0, ellRaw), ellRaw,
    nX: X.nTot, nZ: Z.nTot, sX0: X.s0, sX1: X.s1, sZ1: Z.s1,
    vZ1, phiX, leakEC, tau0, tau1, penalty,
  };
}

/** Bridge the analytic channel model to Lim's per-intensity counts. */
export function limCountsFromChannel(p: {
  N: number; qx: number; mus: number[]; ps: number[];
  Y0: number; etaTotal: number; eD: number;
}) {
  const Q = p.mus.map((k) => gainQmu(p.Y0, p.etaTotal, k));
  const E = p.mus.map((k) => qberEmu(p.Y0, p.etaTotal, p.eD, k));
  const nXk = p.ps.map((pk, i) => p.N * p.qx * p.qx * pk * Q[i]);
  const nZk = p.ps.map((pk, i) => p.N * (1 - p.qx) * (1 - p.qx) * pk * Q[i]);
  return {
    nXk, nZk,
    mXk: nXk.map((n, i) => n * E[i]),
    mZk: nZk.map((n, i) => n * E[i]),
  };
}

export function skrFinite(p: {
  Y0: number; etaTotal: number; eD: number;
  mu: number; nu1: number; nu2: number; fEC: number; N: number; eps: number;
  qx?: number; pMu?: number; pNu1?: number; pNu2?: number; epsCor?: number;
}): number {
  const qx = p.qx ?? 0.5;
  const ps = [p.pMu ?? 0.70, p.pNu1 ?? 0.15, p.pNu2 ?? 0.15];
  const epsCor = p.epsCor ?? 1.0e-15;
  if (p.N <= 0 || !(p.eps > 0 && p.eps < 1)) return 0.0;
  const mus = [p.mu, p.nu1, p.nu2];
  if (!(p.mu > p.nu1 + p.nu2 && p.nu1 > p.nu2 && p.nu2 >= 0)) return 0.0;
  const c = limCountsFromChannel({
    N: p.N, qx, mus, ps, Y0: p.Y0, etaTotal: p.etaTotal, eD: p.eD,
  });
  const r = limKeyLength({
    nXk: c.nXk, nZk: c.nZk, mXk: c.mXk, mZk: c.mZk,
    mus, ps, epsSec: p.eps, epsCor, fEC: p.fEC,
  });
  return r.ell / p.N;
}

/** Convenience: derive Y0 (dark-count yield) and η_total from device params. */
export function channelFromParams(p: {
  detectorEfficiency: number; fiberAttenuationDbPerKm: number;
  linkLengthKm: number; darkCountRateHz: number; pulseRateHz: number;
}): { etaTotal: number; Y0: number } {
  const etaTotal = totalTransmittance(
    p.detectorEfficiency, p.fiberAttenuationDbPerKm, p.linkLengthKm);
  const Y0 = p.darkCountRateHz / Math.max(p.pulseRateHz, 1.0);
  return { etaTotal, Y0 };
}


/**
 * Bundled offline defaults, mirroring `config/qkd_params.yaml`.
 *
 * One definition, because there were three. `BB84.tsx` carried these values,
 * while `bb84Sim.ts` and `bb84.worker.ts` each carried a hardcoded
 * `{ etaTotal: 0.02, Y0: 1e-5 }` describing a DIFFERENT channel -- 6.3x more
 * lossy with 100x the dark count than the configured one. The worker starts
 * immediately to give the page instant data, so those wrong values were what
 * the first rounds were computed from until `/api/sim/params` arrived.
 *
 * Note what is primitive and what is not: eta_total and Y0 are DERIVED from
 * detector efficiency, attenuation, length, dark-count rate and pulse rate.
 * Hardcoding them as if they were inputs is what let them drift out of step
 * with the parameters they are supposed to follow. Nothing here is a derived
 * quantity; call `channelFromParams` for those.
 *
 * `tests/test_frontend_defaults_match_config.py` compares these against
 * config/qkd_params.yaml so the two cannot separate again.
 */
export const BUNDLED_PARAMS = {
  detectorEfficiency: 0.2,
  fiberAttenuationDbPerKm: 0.2,
  linkLengthKm: 10,
  darkCountRateHz: 100,
  pulseRateHz: 1e9,
  misalignmentErrorEd: 0.015,
  /** protocol.qber_threshold_abort */
  qberThresholdAbort: 0.11,
} as const;

/** Channel implied by `BUNDLED_PARAMS`, for engines that need one before config lands. */
export function bundledChannel(): { etaTotal: number; Y0: number; eD: number } {
  const { etaTotal, Y0 } = channelFromParams(BUNDLED_PARAMS);
  return { etaTotal, Y0, eD: BUNDLED_PARAMS.misalignmentErrorEd };
}
