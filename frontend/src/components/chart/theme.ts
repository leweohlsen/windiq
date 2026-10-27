/** Shared chart look — one palette and one axis style so the hand-rolled
 * visx charts read as a coherent, modern set. Change it here and every
 * chart follows. */
export const CHART = {
  /** Primary series: energy bars, power curve, brush sparkline. */
  blue: "#3b82f6",
  /** Energy/yield bars — the Ertrag. */
  green: "#10b981",
  /** Secondary series: wind lines, min/max band, wind rose. */
  violet: "#8b5cf6",
  /** QC flags: interpolated gap hours. */
  amber: "#f59e0b",
  /** Hairline grid. */
  grid: "#eef1f6",
  /** Axis tick labels. */
  axis: "#94a3b8",
  /** Reference/annotation lines (rated power, cut-in/out, rose labels). */
  marker: "#64748b",
  /** Hover crosshair. */
  hover: "#8a94a6",
} as const;

/** Spread onto any visx Axis for the label-only look: no domain line, no
 * tick marks, just quiet gray numbers. */
export const axisProps = {
  hideAxisLine: true,
  hideTicks: true,
  tickLabelProps: { fill: CHART.axis, fontFamily: "inherit", fontSize: 11, fontWeight: 500 },
} as const;
