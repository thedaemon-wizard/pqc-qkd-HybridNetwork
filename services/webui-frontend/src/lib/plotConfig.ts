/**
 * The one Plotly `config` every chart on this site uses.
 *
 * plotly.js 4.0.0 (2026-08-24, plotly/plotly.js#7909) turned `showSendToCloud`
 * ON by default and pointed `plotlyServerURL` at cloud.plotly.com: a modebar
 * button that, after a confirmation step, uploads the chart's data to Plotly's
 * server. On 3.x it was off. Bumping plotly.js to close the maplibre-gl advisory
 * would have added that button to every chart here without a line of this
 * project's code changing -- on a demo whose rule is that visitor-side results
 * stay in the visitor's browser.
 *
 * So the setting is stated, not inherited, and in one place:
 * plotConfigIsPinned.test.ts fails if a <Plot> is given any other config.
 */
export const PLOT_CONFIG = Object.freeze({
  displaylogo: false,
  showSendToCloud: false,
});
