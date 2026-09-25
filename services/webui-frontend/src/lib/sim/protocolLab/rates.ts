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
import { BUNDLED_PARAMS, gainQmu, skrBpsForLink, transmittanceFromLossDb } from "../keyrate";
import { MODEL_ELIGIBLE, quantityValue, type PresetLink } from "./publishedNetworks";

export const MODEL_LABEL =
  "model (this project): this repository's decoy-BB84 finite-key rate, with config/qkd_params.yaml source and detector parameters, applied to the reported loss";

export type ModelRate =
  | { bps: number; lossShown: string }
  | { bps: null; why: string };

export function modelRateFor(link: PresetLink): ModelRate {
  if (link.kind !== "qkd") return { bps: null, why: "not a QKD link" };
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
 * This project's model beside a MEASURED field link, for /physics's read-only
 * field-reference panel.
 *
 * Two model values, both at the link's reported loss and with every other
 * parameter from the shipped configuration:
 *   atShippedMisalignment -- the model as configured;
 *   atMeasuredQber        -- misalignment set so the model's QBER equals the
 *                            measured one (the only way to make the model's
 *                            error rate match the link's).
 * Neither is a prediction for the link: the Thuringia links run entanglement-
 * based BBM92, which this weak-coherent decoy-BB84 model does not describe.
 * Where the source gives the loss as a lower bound (">"), the model value is
 * an UPPER bound on what the model would give on the real, lossier link.
 */
export interface FieldComparison {
  lossShown: string;
  lossIsLowerBound: boolean;
  atShippedMisalignment: number;
  atMeasuredQber: number | null;
  impliedMisalignment: number | null;
}

export function fieldComparison(link: PresetLink): FieldComparison | null {
  if (!link.loss || !link.qber) return null;
  const lossDb = quantityValue(link.loss);
  const measured = quantityValue(link.qber);
  const p = BUNDLED_PARAMS;
  const etaTotal = p.detectorEfficiency * transmittanceFromLossDb(lossDb);
  const Y0 = p.darkCountRateHz / Math.max(p.pulseRateHz, 1.0);
  const q = gainQmu(Y0, etaTotal, p.intensitySignalMu);
  const signal = 1 - Math.exp(-etaTotal * p.intensitySignalMu);
  // E = (Y0/2 + e_d * signal) / Q, solved for e_d. Out of [0, 0.5] means no
  // misalignment reproduces the measured QBER at this loss.
  const eD = signal > 0 ? (measured * q - Y0 / 2) / signal : null;
  const feasible = eD !== null && eD >= 0 && eD <= 0.5;
  const qual = link.loss.qualifier ?? "";
  const sep = qual && !["~", ">", "<"].includes(qual) ? " " : "";
  return {
    lossShown: `${qual}${sep}${link.loss.printed} dB`,
    lossIsLowerBound: qual === ">",
    atShippedMisalignment: skrBpsForLink(p, { lossDb }),
    atMeasuredQber: feasible ? skrBpsForLink({ ...p, misalignmentErrorEd: eD! }, { lossDb }) : null,
    impliedMisalignment: feasible ? eD : null,
  };
}
