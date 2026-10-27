/** Coordinate helpers for the hand-rolled visx charts. */

/** Indices 0..count-1 spaced so their axis labels stay ~minGap px wide —
 * the hand-rolled stand-in for recharts' minTickGap. */
export function strideTicks(count: number, innerWidth: number, minGap: number): number[] {
  if (count <= 0) return [];
  const stride = Math.max(1, Math.ceil((count * minGap) / Math.max(innerWidth, 1)));
  return Array.from({ length: Math.ceil(count / stride) }, (_, i) => i * stride);
}

export function clampIndex(i: number, count: number): number {
  return Math.max(0, Math.min(count - 1, Math.round(i)));
}

/** Bar path with rounded top corners only (svg rect rx would also round
 * the baseline end that sits on the axis). */
export function barPath(x: number, y: number, w: number, h: number, r: number): string {
  const rr = Math.min(r, w / 2, h / 2);
  return [
    `M${x},${y + h}`,
    `L${x},${y + rr}`,
    `Q${x},${y} ${x + rr},${y}`,
    `L${x + w - rr},${y}`,
    `Q${x + w},${y} ${x + w},${y + rr}`,
    `L${x + w},${y + h}`,
    "Z",
  ].join(" ");
}

/** deg 0 = north = up, growing clockwise (the rose's bearing convention). */
export function polarPoint(cx: number, cy: number, r: number, deg: number) {
  const rad = ((deg - 90) * Math.PI) / 180;
  return { x: cx + r * Math.cos(rad), y: cy + r * Math.sin(rad) };
}
