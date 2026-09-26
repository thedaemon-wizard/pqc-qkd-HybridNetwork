import type { CSSProperties } from "react";
import { colors, spacing } from "../lib/commonStyles";
import { useNarrowLayout } from "../lib/layout";
import { PRESETS, presetById, scenariosFor } from "../lib/sim/protocolLab/publishedNetworks";

/**
 * Below the shell's breakpoint each field is its caption over a select as wide
 * as the panel. A <select> is as wide as its longest option, and the scenario
 * titles are long: "Tokyo secure TV conference: attack and switch-over" made
 * the Scenario select 343px, which at a 320px viewport ran 78px out of its
 * 264px panel and scrolled the whole page 51px sideways (measured 2026-09-26).
 * Capped at the panel's width the select shows as much of the title as fits,
 * and the phone's own picker lists every option in full.
 */
const NARROW_FIELD: CSSProperties = {
  display: "flex", flexDirection: "column", gap: spacing.xs, flex: "1 1 100%", minWidth: 0,
};
const NARROW_SELECT: CSSProperties = { width: "100%", minWidth: 0 };

/** The Scenario select's first option: no scenario, the reader drives the run. */
const FREE_PLAY = "Free play";

/** Preset and scenario selectors, with the source's citation and licence beneath. */
export default function LoadPresetDropdown({ presetId, scenarioId, onChange }: {
  presetId: string;
  scenarioId: string | null;
  onChange: (presetId: string, scenarioId: string | null) => void;
}) {
  const narrow = useNarrowLayout();
  const preset = presetById(presetId);
  const scenarios = scenariosFor(presetId);
  // The chosen option's full text as the Scenario select's title, below 768px
  // only: there the capped select shows only the start of a long title
  // ("Tokyo secure TV conference: attack an" at 320px), and the title is
  // where the rest is, short of opening the picker. From 768px up the select
  // is as wide as its longest option, so a title would only add a hover
  // tooltip and, beside the aria-label, a second reading of the value as the
  // select's description. A scenario id with no option here gets no title
  // rather than a guessed one.
  const scenarioTitle = scenarioId === null ? FREE_PLAY : scenarios.find((s) => s.id === scenarioId)?.title;
  const select = { background: colors.panelDark, color: colors.textPri,
                   border: `1px solid ${colors.borderLt}`, borderRadius: 4, padding: "4px 6px",
                   ...(narrow ? NARROW_SELECT : {}) };
  const field = { fontSize: 12, color: colors.textSec, ...(narrow ? NARROW_FIELD : {}) };
  return (
    <div>
      <div style={{ display: "flex", gap: 12, flexWrap: "wrap", alignItems: "center" }}>
        <label style={field}>
          Network{" "}
          <select aria-label="Published network" value={presetId} style={select}
                  onChange={(e) => onChange(e.target.value, null)}>
            {PRESETS.map((p) => <option key={p.meta.id} value={p.meta.id}>{p.meta.title}</option>)}
          </select>
        </label>
        <label style={field}>
          Scenario{" "}
          <select aria-label="Cited scenario" value={scenarioId ?? ""} style={select}
                  title={narrow ? scenarioTitle : undefined}
                  onChange={(e) => onChange(presetId, e.target.value || null)}>
            <option value="">{FREE_PLAY}</option>
            {scenarios.map((s) => <option key={s.id} value={s.id}>{s.title}</option>)}
          </select>
        </label>
      </div>
      {/* A DOI is one unbreakable token; break-word lets it wrap only if it
          alone would run past the panel, and leaves every other line as is. */}
      <div style={{ fontSize: 11, color: colors.textMute, marginTop: 6, overflowWrap: "break-word" }}>
        Source: {preset.meta.citation}{" "}
        (<a href={preset.meta.url} target="_blank" rel="noreferrer" style={{ color: colors.accent }}>
          {preset.meta.doi ? `doi:${preset.meta.doi}` : `arXiv:${preset.meta.arxiv}`}
        </a>). Licence: {preset.meta.licence}. {preset.meta.reuseNote}
      </div>
    </div>
  );
}
