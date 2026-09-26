import { colors } from "../lib/commonStyles";
import ScrollRegion from "./ScrollRegion";
import { formatRate, formatReported } from "../lib/formatRate";
import { presetById, type PresetLink } from "../lib/sim/protocolLab/publishedNetworks";
import { fieldComparison, type FieldComparison } from "../lib/sim/protocolLab/rates";

/**
 * /physics: measured field values from arXiv:2608.18869v2 beside what this
 * project's model gives at the same loss. Read-only by construction -- it takes
 * no props and calls no setter, so nothing here can move the parameters the
 * page edits (fieldReferenceIsReadOnly.test.ts).
 *
 * It used to set "the model gives 0 bit/s at the measured QBER" against "the
 * links distilled 12.7 and 22.2 bps", which reads as a gap between model and
 * reality. The source explains most of it: Table I's QBERs are campaign
 * averages with temporal standard deviations, and SND-ERF's key came only from
 * the intervals in which its QBER stayed low. The panel now shows what the
 * model tolerates at each loss and says, per link, why its value is what it is.
 */

const pct = (x: number | null) => (x === null ? "none" : `${(x * 100).toFixed(2)} %`);
/** A block size as the config writes it, e.g. 1e9. */
const pulses = (n: number) => n.toExponential(0).replace("+", "");

/**
 * Why the model's value for this link is what it is, from the model itself.
 * Exported for fieldReferenceIsReadOnly.test.ts, which checks that each
 * sentence says only what its comparison supports.
 *
 * Both tolerances come from the same finite-key model the KMEs use; the second
 * is at a block large enough that a larger one prints the same value
 * (LARGE_BLOCK_N in rates.ts). "No block size gives key" is said only when the
 * mean is above that one by more than the precision the source printed it
 * with: ERF-IOF's 6.1 % stands for 6.05-6.15 %, and the model's large-block
 * tolerance at its loss is 6.06 %, so there the printed mean does not settle
 * it and the sentence says so instead.
 */
export function modelReasons(c: FieldComparison, l: PresetLink): string[] {
  const out: string[] = [];
  if (c.pastLossCutoff) {
    out.push(`The reported loss is at or past the loss at which the shipped configuration stops distilling key (${c.lossCutoffDb.toFixed(1)} dB at N = ${pulses(c.blockSizeN)} pulses); that cut-off moves with the block size and the misalignment.`);
  }
  const mean = `The campaign-mean QBER (${formatReported(l.qber)})`;
  const shipped = `the model's tolerance at N = ${pulses(c.blockSizeN)} pulses (${pct(c.qberTolerance)})`;
  const large = `the model's large-block tolerance (${pct(c.qberToleranceLargeBlock)} at N = ${pulses(c.largeBlockN)})`;
  if (c.meanVsLargeBlockTolerance === "above") {
    out.push(`${mean} is above ${large} at this loss, so no block size gives key at a constant QBER equal to the mean.`);
  } else if (c.meanVsLargeBlockTolerance === "level") {
    out.push(`${mean} is `
      + (c.meanVsTolerance === "above" ? `above ${shipped} and ` : "")
      + `level with ${large} at this loss to the precision the source prints, so the model does not settle whether a large enough block would give key at a constant QBER equal to the mean.`);
  } else if (c.meanVsTolerance === "above") {
    out.push(`${mean} is above ${shipped} but below ${large}.`);
  } else if (c.meanVsTolerance === "level") {
    out.push(`${mean} is level with ${shipped} to the precision the source prints, and below ${large}.`);
  }
  return out;
}

export default function FieldReferencePanel() {
  const preset = presetById("thuringia-2026");
  const rows = preset.links.filter((l) => l.kind === "qkd");
  const cell = { padding: "3px 8px", borderBottom: `1px solid ${colors.border}`, verticalAlign: "top" as const };
  const rate = (bps: number) => {
    const r = formatRate(bps);
    return `${r.value} ${r.unit}`;
  };
  const split = (l: PresetLink) => [l.aerial && `${formatReported(l.aerial)} aerial`, l.buried && `${formatReported(l.buried)} buried`]
    .filter(Boolean).join(", ");
  return (
    <div style={{ background: colors.panelBg, border: `1px solid ${colors.border}`, borderRadius: 8, padding: 14, marginTop: 16 }}>
      <h3 style={{ margin: "0 0 6px 0", fontSize: 14, color: colors.textSec }}>
        Field reference (arXiv:2608.18869v2, read-only)
      </h3>
      <p style={{ fontSize: 11, color: colors.textMute, marginTop: 0 }}>
        Measured on two deployed links in Thuringia. They run entanglement-based BBM92;
        this page's model is weak-coherent decoy-state BB84, so the two describe different
        protocols. The measured QBERs are averages over each campaign and the ± values are
        temporal standard deviations (section IV.A), so a link spent time well above and
        well below its mean. The model values use the shipped configuration at each link's
        reported loss; they are shown beside the measurement, never fitted to it, and
        nothing here changes the parameters above.
      </p>
      {/* Measured 2026-09-26: 572px of table in a 313px box at 375px and a
          454px box at 768px, so it scrolls at both; ScrollRegion names it and
          makes it a Tab stop while it does. */}
      <ScrollRegion aria-label="Field reference table">
        <table style={{ borderCollapse: "collapse", fontSize: 12, color: colors.textSec, width: "100%" }}>
          <thead>
            <tr>{["Link", "Length", "Loss", "Campaign", "Measured SKR", "Measured QBER", "Model, shipped configuration", "Model's QBER tolerance at this loss"].map((h) =>
              <th key={h} style={{ ...cell, textAlign: "left", color: colors.textPri }}>{h}</th>)}</tr>
          </thead>
          <tbody>
            {rows.map((l) => {
              const c = fieldComparison(l);
              return (
                <tr key={l.id}>
                  <td style={cell}><code>{l.id}</code></td>
                  <td style={cell}>{formatReported(l.length)}
                    {split(l) && <span style={{ color: colors.textMute }}> ({split(l)})</span>}
                  </td>
                  <td style={cell}>{formatReported(l.loss)}</td>
                  <td style={cell}>{l.campaign ? formatReported(l.campaign) : "not reported"}</td>
                  <td style={cell} title={l.rate?.ref}>{formatReported(l.rate)}</td>
                  <td style={cell} title={l.qber?.ref}>{formatReported(l.qber)}</td>
                  <td style={cell}>{c ? rate(c.atShippedMisalignment) : "--"}</td>
                  <td style={cell}>{c ? `${pct(c.qberTolerance)} at N = ${pulses(c.blockSizeN)}; ${pct(c.qberToleranceLargeBlock)} at N = ${pulses(c.largeBlockN)} (the model's large-block tolerance)` : "--"}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </ScrollRegion>
      <ul style={{ fontSize: 11, color: colors.textMute, margin: "8px 0 0", paddingLeft: 18 }}>
        {rows.map((l) => {
          const c = fieldComparison(l);
          const reasons = c ? modelReasons(c, l) : [];
          return (
            <li key={l.id} style={{ marginBottom: 4 }}>
              <code>{l.id}</code>:{" "}
              {reasons.length ? reasons.join(" ") : "The model distils key at this loss with the shipped configuration."}{" "}
              {l.notes.length > 0 && <>Source: {l.notes.join(" ")}</>}
            </li>
          );
        })}
      </ul>
      <p style={{ fontSize: 11, color: colors.textMute, marginBottom: 0 }}>
        {rows.some((l) => fieldComparison(l)?.lossIsLowerBound)
          ? "The losses are given as lower bounds, so each model value is an upper bound on what the model would give on the real link. " : ""}
        A model value at a constant QBER equal to a campaign mean is not a prediction of
        the measured rate, and is not shown.{" "}
        Source: <a href={preset.meta.url} target="_blank" rel="noreferrer" style={{ color: colors.accent }}>{preset.meta.citation}</a>,
        Table I ({preset.meta.licence}).
      </p>
    </div>
  );
}
