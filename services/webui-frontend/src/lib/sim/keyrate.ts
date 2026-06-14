/**
 * Closed-form QKD key-rate — faithful TypeScript port of
 * services/bb84-kme/app/backends/_skr.py (Lo-Ma two-decoy, PRL 94 230504 2005;
 * finite-key correction arXiv:2511.21253). Pure functions; the single source of
 * truth for the client-side Physics + BB84 numbers (no backend).
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
  const denom = mu * nu1 - nu1 * nu1;
  let Y1_L = (mu / denom) * (
    Q_nu1 * Math.exp(nu1) - Q_nu2 * Math.exp(nu2)
    - ((nu1 * nu1 - nu2 * nu2) / (mu * mu)) * (Q_mu * Math.exp(mu) - Y0)
  );
  Y1_L = Math.max(Y1_L, 0.0);
  if (Y1_L <= 0 || nu1 <= 0) return 0.0;
  let e1_U = (E_nu1 * Q_nu1 * Math.exp(nu1) - 0.5 * Y0) / (Y1_L * nu1);
  e1_U = Math.max(0.0, Math.min(0.5, e1_U));
  const Q1 = mu * Math.exp(-mu) * Y1_L;
  const rate = 0.5 * (-Q_mu * fEC * H2(E_mu) + Q1 * (1.0 - H2(e1_U)));
  return Math.max(rate, 0.0);
}

/** arXiv:2511.21253 first-order finite-size correction term. */
export function finiteKeyPenalty(N: number, eps: number): number {
  if (N <= 0 || eps <= 0) return 0.0;
  return Math.sqrt(2.0 / N) * Math.sqrt(Math.log2(2.0 / eps));
}

export function skrFinite(p: {
  Y0: number; etaTotal: number; eD: number;
  mu: number; nu1: number; nu2: number; fEC: number; N: number; eps: number;
}): number {
  const R = asymptoticSkrPerPulse(p);
  return Math.max(0.0, R - finiteKeyPenalty(p.N, p.eps));
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
