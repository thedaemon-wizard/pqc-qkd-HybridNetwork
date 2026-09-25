import { colors } from "../lib/commonStyles";
import { formatRate, formatReported } from "../lib/formatRate";
import { presetById } from "../lib/sim/protocolLab/publishedNetworks";
import { fieldComparison } from "../lib/sim/protocolLab/rates";

/**
 * /physics: measured field values from arXiv:2608.18869v2 beside what this
 * project's model gives at the same loss. Read-only by construction -- it takes
 * no props and calls no setter, so nothing here can move the parameters the
 * page edits (fieldReferenceIsReadOnly.test.ts).
 */
export default function FieldReferencePanel() {
  const preset = presetById("thuringia-2026");
  const rows = preset.links.filter((l) => l.kind === "qkd");
  const cell = { padding: "3px 8px", borderBottom: `1px solid ${colors.border}`, verticalAlign: "top" as const };
  const rate = (bps: number | null) => {
    if (bps === null) return "no misalignment reproduces it";
    const r = formatRate(bps);
    return `${r.value} ${r.unit}`;
  };
  return (
    <div style={{ background: colors.panelBg, border: `1px solid ${colors.border}`, borderRadius: 8, padding: 14, marginTop: 16 }}>
      <h3 style={{ margin: "0 0 6px 0", fontSize: 14, color: colors.textSec }}>
        Field reference (arXiv:2608.18869v2, read-only)
      </h3>
      <p style={{ fontSize: 11, color: colors.textMute, marginTop: 0 }}>
        Measured on two deployed links in Thuringia. They run entanglement-based BBM92;
        this page's model is weak-coherent decoy-state BB84, so the two describe different
        protocols. The model values use the shipped configuration at each link's reported
        loss; they are shown beside the measurement, never fitted to it, and nothing here
        changes the parameters above.
      </p>
      <div style={{ overflowX: "auto" }}>
        <table style={{ borderCollapse: "collapse", fontSize: 12, color: colors.textSec, width: "100%" }}>
          <thead>
            <tr>{["Link", "Length", "Loss", "Measured SKR", "Measured QBER", "Model, shipped misalignment", "Model, misalignment matched to the QBER"].map((h) =>
              <th key={h} style={{ ...cell, textAlign: "left", color: colors.textPri }}>{h}</th>)}</tr>
          </thead>
          <tbody>
            {rows.map((l) => {
              const c = fieldComparison(l);
              return (
                <tr key={l.id}>
                  <td style={cell}><code>{l.id}</code></td>
                  <td style={cell}>{formatReported(l.length)}</td>
                  <td style={cell}>{formatReported(l.loss)}</td>
                  <td style={cell} title={l.rate?.ref}>{formatReported(l.rate)}</td>
                  <td style={cell} title={l.qber?.ref}>{formatReported(l.qber)}</td>
                  <td style={cell}>{c ? rate(c.atShippedMisalignment) : "--"}</td>
                  <td style={cell}>{c ? rate(c.atMeasuredQber) : "--"}
                    {c?.impliedMisalignment != null && (
                      <span style={{ color: colors.textMute }}> (e_d = {c.impliedMisalignment.toFixed(3)})</span>)}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p style={{ fontSize: 11, color: colors.textMute, marginBottom: 0 }}>
        {rows.some((l) => fieldComparison(l)?.lossIsLowerBound)
          ? "The losses are given as lower bounds, so each model value is an upper bound on what the model would give on the real link. " : ""}
        At the measured QBER this model distils key on{" "}
        {rows.filter((l) => (fieldComparison(l)?.atMeasuredQber ?? 0) > 0).length} of {rows.length} links;
        the links themselves distilled {rows.map((l) => formatReported(l.rate)).join(" and ")}.
        Source: {preset.meta.citation}, Table I ({preset.meta.licence}).
      </p>
    </div>
  );
}
