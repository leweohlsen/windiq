/** Tooltip box anchored at (left, top) inside the relative .chart-inner
 * wrapper, raised above the anchor point and clamped to the chart width.
 * The .tooltip styling lives in styles.css. */
import type { ReactNode } from "react";

export function ChartTooltip({
  left,
  top,
  width,
  children,
}: {
  left: number;
  top: number;
  width: number;
  children: ReactNode;
}) {
  const x = Math.max(60, Math.min(width - 60, left));
  return (
    <div className="tooltip-wrap" style={{ left: x, top }}>
      <div className="tooltip">{children}</div>
    </div>
  );
}
