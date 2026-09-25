/**
 * This project's model rate for a published link -- shown beside the reported
 * rate in /protocol-lab's link table, never used to drive the simulation.
 *
 * The only caller of `skrBpsForLink` (protocolLabSim.test.ts checks). The model
 * is this repository's decoy-BB84 finite-key rate with its own source and
 * detector parameters (config/qkd_params.yaml, via BUNDLED_PARAMS) applied to
 * the span's REPORTED loss. It is not a prediction for the vendor's system,
 * which has its own detectors, intensities and block sizes: on SECOQC's 7.5 dB
 * link it gives about 0.9 Mbit/s against 3.1 kbit/s reported.
 *
 * It is null unless the link runs decoy-state BB84 over fibre with a reported
 * loss. No loss is estimated from a length, because that would put a number on
 * screen the source did not give.
 */
import {
  BUNDLED_PARAMS, qberEmu, skrBpsForLink, transmittanceFromLossDb,
} from "../keyrate";
import {
  MODEL_ELIGIBLE, quantityHalfStep, quantityValue, type PresetLink,
} from "./publishedNetworks";

/**
 * A misalignment above 1/2 is a relabelling of the bases (the same bound
 * /physics puts on `physical.misalignment_error_ed`), so the search stops there.
 */
const MAX_MISALIGNMENT = 0.5;

export const MODEL_LABEL =
  "model (this project): this repository's decoy-BB84 finite-key rate, with config/qkd_params.yaml source and detector parameters, applied to the reported loss";

export type ModelRate =
  | { bps: number; lossShown: string }
  | { bps: null; why: string };

export function modelRateFor(link: PresetLink): ModelRate {
  // The only non-"qkd" kind is Thuringia's keystore hop, whose source says the
  // keys were previously generated and stored, not how -- so this names what the
  // hop is ("not live QKD") rather than calling it "not QKD".
  if (link.kind !== "qkd") return { bps: null, why: "keystore hop (not live QKD): no key-rate model applies" };
  if (!MODEL_ELIGIBLE.includes(link.protocol)) {
    return { bps: null, why: `${link.protocol}: the model describes decoy-state BB84 only` };
  }
  if (link.medium !== "fibre") return { bps: null, why: "not a fibre link" };
  if (!link.loss) return { bps: null, why: "no reported loss" };
  const bps = skrBpsForLink(BUNDLED_PARAMS, { lossDb: quantityValue(link.loss) });
  const qual = link.loss.qualifier ? `${link.loss.qualifier}` : "";
  const sep = qual && !["~", ">", "<"].includes(qual) ? " " : "";
  return { bps, lossShown: `${qual}${sep}${link.loss.printed} dB` };
}

/**
 * Bisection steps for the searches below. Each step halves the bracket; 60
 * halvings take a 0.5-wide misalignment bracket below 1e-18, past what a
 * double can distinguish, so more steps cannot change the answer.
 */
const BISECTION_STEPS = 60;

/**
 * Upper end of the loss search. Chosen to lie beyond any loss at which this
 * model distils key for the shipped configuration (its cut-off is about 20 dB
 * at N = 1e9 pulses), so the search always brackets the cut-off; it is a
 * search bound, not a physical claim.
 */
const LOSS_SEARCH_MAX_DB = 100;

/** Largest x in [lo, hi] with ok(x) true, for ok true at lo and monotone. */
function edge(ok: (x: number) => boolean, lo: number, hi: number): number {
  for (let i = 0; i < BISECTION_STEPS; i++) {
    const mid = (lo + hi) / 2;
    if (ok(mid)) lo = mid; else hi = mid;
  }
  return lo;
}

/**
 * The block size at which /physics reports the model's large-block QBER
 * tolerance: the same finite-key model the KMEs use (`skrBpsForLink`), at a
 * block large enough that a larger one would print the same value.
 *
 * Measured on the shipped configuration at both Thuringia losses: from 1e18
 * pulses to 1e30 the tolerance moves by less than 0.001 percentage points
 * (6.0632 to 6.0634 % at 17 dB, 6.0596 to 6.0599 % at 21 dB), a tenth of the
 * 0.01 % the panel prints. At 1e15 it is still 0.006 and 0.010 points short,
 * which can change the printed digit. fieldReferenceIsReadOnly.test.ts
 * re-measures both, so a change to the model or the configuration that moves
 * the limit fails there rather than printing a value that is not converged.
 *
 * This replaced a Lo-Ma closed-form "asymptotic" tolerance, which is a
 * different formula and not this model's limit: it gave 5.96 % and 5.95 %,
 * below what the finite-key model itself tolerates from about 1e13 pulses on.
 */
export const LARGE_BLOCK_N = 1e18;

/**
 * Where a source's printed campaign-mean QBER stands against a tolerance:
 *   "above" -- above it by more than the precision the source printed;
 *   "below" -- below it by more than that precision;
 *   "level" -- within half a unit of the last printed digit, so the printed
 *              number does not settle which side of the tolerance the mean
 *              is on.
 * A null tolerance (no key at this loss even with zero misalignment) counts
 * as "above".
 */
export type MeanVsTolerance = "above" | "level" | "below";

/**
 * This project's model beside a MEASURED field link, for /physics's read-only
 * field-reference panel. Every value uses the link's reported loss and the
 * shipped configuration for everything else.
 *
 *   atShippedMisalignment    -- the model's rate as configured;
 *   qberTolerance            -- the highest QBER at which the model still
 *                               distils key at this loss with the shipped
 *                               block size (found by raising the
 *                               misalignment until the rate reaches zero);
 *   qberToleranceLargeBlock  -- the same, from the same finite-key model, at
 *                               LARGE_BLOCK_N pulses: the model's large-block
 *                               tolerance;
 *   lossCutoffDb             -- the loss at which the shipped configuration
 *                               stops distilling key.
 *
 * This used to report the model's rate "at the measured QBER", with the
 * misalignment solved so the model's QBER equalled the link's. That set a
 * constant error rate equal to the campaign MEAN against the links' measured
 * key, and the source explains why that comparison fails: for SND-ERF the mean
 * QBER is above the key-generation threshold and key came only from intervals
 * in which the instantaneous QBER stayed low (arXiv:2608.18869v2 section IV.A).
 * It also attributed a wind-driven, time-varying QBER to a fixed misalignment.
 * The tolerance says what the model can take without claiming either.
 *
 * Neither value is a prediction for the link: the Thuringia links run
 * entanglement-based BBM92, which this weak-coherent decoy-BB84 model does not
 * describe. Where the source gives the loss as a lower bound (">"), the model
 * value is an UPPER bound on what the model would give on the real, lossier
 * link.
 */
export interface FieldComparison {
  lossShown: string;
  lossIsLowerBound: boolean;
  atShippedMisalignment: number;
  /** Null when the model gives no key at this loss even with zero misalignment. */
  qberTolerance: number | null;
  /** The misalignment at which the model's QBER equals `qberTolerance`. */
  toleranceMisalignment: number | null;
  /** `qberTolerance` at LARGE_BLOCK_N pulses instead of the shipped block size. */
  qberToleranceLargeBlock: number | null;
  /** The block size `qberToleranceLargeBlock` assumes (LARGE_BLOCK_N). */
  largeBlockN: number;
  lossCutoffDb: number;
  /** The block size the finite-key values assume (BUNDLED_PARAMS.blockSizeN). */
  blockSizeN: number;
  /** The reported loss is at or past `lossCutoffDb`. */
  pastLossCutoff: boolean;
  /** The measured campaign-mean QBER against `qberTolerance`. */
  meanVsTolerance: MeanVsTolerance;
  /** The measured campaign-mean QBER against `qberToleranceLargeBlock`. */
  meanVsLargeBlockTolerance: MeanVsTolerance;
}

export function fieldComparison(link: PresetLink): FieldComparison | null {
  if (!link.loss || !link.qber) return null;
  const lossDb = quantityValue(link.loss);
  const measured = quantityValue(link.qber);
  const halfStep = quantityHalfStep(link.qber);
  const p = BUNDLED_PARAMS;
  const etaTotal = p.detectorEfficiency * transmittanceFromLossDb(lossDb);
  const Y0 = p.darkCountRateHz / Math.max(p.pulseRateHz, 1.0);
  const qber = (eD: number) => qberEmu(Y0, etaTotal, eD, p.intensitySignalMu);

  /** The QBER at which the model stops distilling key at this loss and block size. */
  const toleranceAt = (blockSizeN: number) => {
    const key = (eD: number) =>
      skrBpsForLink({ ...p, blockSizeN, misalignmentErrorEd: eD }, { lossDb }) > 0;
    return key(0) ? edge(key, 0, MAX_MISALIGNMENT) : null;
  };
  const toleranceMisalignment = toleranceAt(p.blockSizeN);
  const largeBlockMisalignment = toleranceAt(LARGE_BLOCK_N);

  const shippedKeyAt = (loss: number) => skrBpsForLink(p, { lossDb: loss }) > 0;
  const lossCutoffDb = edge(shippedKeyAt, 0, LOSS_SEARCH_MAX_DB);

  const qberTolerance = toleranceMisalignment === null ? null : qber(toleranceMisalignment);
  const qberToleranceLargeBlock = largeBlockMisalignment === null ? null : qber(largeBlockMisalignment);
  const against = (tol: number | null): MeanVsTolerance => {
    if (tol === null || measured - halfStep > tol) return "above";
    if (measured + halfStep < tol) return "below";
    return "level";
  };
  const qual = link.loss.qualifier ?? "";
  const sep = qual && !["~", ">", "<"].includes(qual) ? " " : "";
  return {
    lossShown: `${qual}${sep}${link.loss.printed} dB`,
    lossIsLowerBound: qual === ">",
    atShippedMisalignment: skrBpsForLink(p, { lossDb }),
    qberTolerance,
    toleranceMisalignment,
    qberToleranceLargeBlock,
    largeBlockN: LARGE_BLOCK_N,
    lossCutoffDb,
    blockSizeN: p.blockSizeN,
    pastLossCutoff: lossDb >= lossCutoffDb,
    meanVsTolerance: against(qberTolerance),
    meanVsLargeBlockTolerance: against(qberToleranceLargeBlock),
  };
}
