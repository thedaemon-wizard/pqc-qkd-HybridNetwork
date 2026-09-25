import { colors } from "../lib/commonStyles";
import { PRESETS, presetById, scenariosFor } from "../lib/sim/protocolLab/publishedNetworks";

/** Preset and scenario selectors, with the source's citation and licence beneath. */
export default function LoadPresetDropdown({ presetId, scenarioId, onChange }: {
  presetId: string;
  scenarioId: string | null;
  onChange: (presetId: string, scenarioId: string | null) => void;
}) {
  const preset = presetById(presetId);
  const scenarios = scenariosFor(presetId);
  const select = { background: colors.panelDark, color: colors.textPri,
                   border: `1px solid ${colors.borderLt}`, borderRadius: 4, padding: "4px 6px" };
  return (
    <div>
      <div style={{ display: "flex", gap: 12, flexWrap: "wrap", alignItems: "center" }}>
        <label style={{ fontSize: 12, color: colors.textSec }}>
          Network{" "}
          <select aria-label="Published network" value={presetId} style={select}
                  onChange={(e) => onChange(e.target.value, null)}>
            {PRESETS.map((p) => <option key={p.meta.id} value={p.meta.id}>{p.meta.title}</option>)}
          </select>
        </label>
        <label style={{ fontSize: 12, color: colors.textSec }}>
          Scenario{" "}
          <select aria-label="Cited scenario" value={scenarioId ?? ""} style={select}
                  onChange={(e) => onChange(presetId, e.target.value || null)}>
            <option value="">Free play</option>
            {scenarios.map((s) => <option key={s.id} value={s.id}>{s.title}</option>)}
          </select>
        </label>
      </div>
      <div style={{ fontSize: 11, color: colors.textMute, marginTop: 6 }}>
        Source: {preset.meta.citation}{" "}
        (<a href={preset.meta.url} target="_blank" rel="noreferrer" style={{ color: colors.accent }}>
          {preset.meta.doi ? `doi:${preset.meta.doi}` : `arXiv:${preset.meta.arxiv}`}
        </a>). Licence: {preset.meta.licence}. {preset.meta.reuseNote}
      </div>
    </div>
  );
}
