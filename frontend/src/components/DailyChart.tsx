/** Daily chart: bars = daily energy (MWh) with per-bar coloring (clean →
 * accent, no ok hours → gap), line = mean wind (m/s) on the second y-axis;
 * tooltip shows mean/max wind. Title and range switcher live in App's panel
 * head. QC tracking moved to the wind panel (plan 2026-10-27).
 *
 * Hand-rolled SVG via visx primitives (see chart/helpers.ts): one band/point
 * scale for x, two linear y-scales, bar + line paths computed per data
 * change and hover resolved to an index by scale inversion. */
import { memo, useMemo, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";
import { AxisBottom, AxisLeft, AxisRight } from "@visx/axis";
import { scaleLinear, scalePoint } from "@visx/scale";
import { line as d3Line } from "@visx/vendor/d3-shape";

import type { DailyPoint } from "../api";
import { asMs, asMWh } from "../format";
import { ChartTooltip } from "./chart/ChartTooltip";
import { clampIndex, strideTicks } from "./chart/helpers";
import { useChartSize } from "./chart/useChartSize";

const CLEAN = "#3b82f6";
const LINE = "#b45309";
const MUTED = "#667085";
const GRID = "#e4e8ef";

const margin = { top: 12, right: 44, bottom: 28, left: 48 };

type Hover = { idx: number; left: number; top: number };

/** Memoized: per-panel data references stay stable across unchanged polls,
 * so a metrics-only tick never reconciles the (up to 365-point) chart. */
export const DailyChart = memo(function DailyChart({ daily }: { daily: DailyPoint[] }) {
  const { ref, width, height } = useChartSize();
  const svgRef = useRef<SVGSVGElement>(null);
  const [hover, setHover] = useState<Hover | null>(null);

  const chartData = useMemo(
    () =>
      daily.map((point) => ({
        ...point,
        energy_mwh: point.energy_kwh == null ? null : point.energy_kwh / 1000,
      })),
    [daily],
  );

  const n = chartData.length;
  const days = useMemo(() => chartData.map((p) => p.day), [chartData]);

  /* A point scale centers ticks (and thus bars' axis alignment) per day. */
  const xScale = useMemo(
    () =>
      scalePoint<string>({
        domain: days,
        range: [0, Math.max(0, width - margin.left - margin.right)],
        padding: 0.5,
      }),
    [days, width],
  );
  const innerW = Math.max(0, width - margin.left - margin.right);
  const innerH = Math.max(0, height - margin.top - margin.bottom);

  const maxEnergy = Math.max(0.01, ...chartData.map((p) => p.energy_mwh ?? 0));
  const yEnergy = useMemo(
    () => scaleLinear({ domain: [0, maxEnergy * 1.05], range: [innerH, 0] }).nice(),
    [maxEnergy, innerH],
  );
  const maxWind = Math.max(1, ...chartData.map((p) => p.mean_wind_ms ?? 0));
  const yWind = useMemo(
    () => scaleLinear({ domain: [0, maxWind * 1.1], range: [innerH, 0] }).nice(),
    [maxWind, innerH],
  );

  const xTicks = useMemo(() => strideTicks(n, innerW, 40), [n, innerW]);

  const linePath = useMemo(
    () =>
      d3Line<(typeof chartData)[number]>()
        .defined((p) => p.mean_wind_ms != null)
        .x((p) => xScale(p.day)!)
        .y((p) => yWind(p.mean_wind_ms!))(chartData) ?? "",
    [xScale, yWind, chartData],
  );

  const step = xScale.step();
  const barWidth = Math.min(step * 0.7, 28);
  const ready = width > 0 && n > 0;

  const onMove = (e: ReactPointerEvent) => {
    const rect = svgRef.current?.getBoundingClientRect();
    if (!rect) return;
    const px = e.clientX - rect.left - margin.left;
    if (px < -10 || px > innerW + 10) {
      setHover(null);
      return;
    }
    const idx = clampIndex((px - xScale(days[0]!)!) / step, n);
    const point = chartData[idx]!;
    setHover({
      idx,
      left: xScale(point.day)! + margin.left,
      top: yEnergy(point.energy_mwh ?? maxEnergy) + margin.top,
    });
  };

  const hovered = hover != null ? (chartData[hover.idx] ?? null) : null;

  return (
    <div className="chart">
      <div ref={ref} className="chart-inner">
        {ready && (
          <svg ref={svgRef} width={width} height={height}>
            <g transform={`translate(${margin.left},${margin.top})`}>
              <g>
                {yEnergy.ticks(4).map((t) => (
                  <line
                    key={`h${t}`}
                    x1={0}
                    x2={innerW}
                    y1={yEnergy(t)}
                    y2={yEnergy(t)}
                    stroke={GRID}
                    strokeDasharray="3 3"
                  />
                ))}
                {xTicks.map((i) => (
                  <line
                    key={`v${i}`}
                    x1={xScale(days[i]!)}
                    x2={xScale(days[i]!)}
                    y1={0}
                    y2={innerH}
                    stroke={GRID}
                    strokeDasharray="3 3"
                  />
                ))}
              </g>
              {chartData.map((p) =>
                p.energy_mwh == null ? null : (
                  <rect
                    key={p.day}
                    x={xScale(p.day)! - barWidth / 2}
                    y={yEnergy(p.energy_mwh)}
                    width={barWidth}
                    height={innerH - yEnergy(p.energy_mwh)}
                    fill={CLEAN}
                  />
                ),
              )}
              <path d={linePath} fill="none" stroke={LINE} strokeWidth={2} />
              <AxisBottom
                top={innerH}
                scale={xScale}
                tickValues={xTicks.map((i) => days[i]!)}
                tickFormat={(day) => day.slice(5)}
                tickLength={4}
                stroke={GRID}
                tickStroke={GRID}
                tickLabelProps={{ fill: MUTED, fontFamily: "inherit", fontSize: 11 }}
              />
              <AxisLeft
                scale={yEnergy}
                tickFormat={(v) => Number(v).toFixed(0)}
                tickLength={4}
                stroke={GRID}
                tickStroke={GRID}
                tickLabelProps={{ fill: MUTED, fontFamily: "inherit", fontSize: 11 }}
              />
              <AxisRight
                scale={yWind}
                tickFormat={(v) => Number(v).toFixed(0)}
                tickLength={4}
                stroke={GRID}
                tickStroke={GRID}
                tickLabelProps={{ fill: MUTED, fontFamily: "inherit", fontSize: 11 }}
              />
              {hover && (
                <g pointerEvents="none">
                  <line
                    x1={xScale(days[hover.idx]!)}
                    x2={xScale(days[hover.idx]!)}
                    y1={0}
                    y2={innerH}
                    stroke={MUTED}
                    strokeDasharray="3 3"
                    opacity={0.5}
                  />
                </g>
              )}
              <rect
                x={0}
                y={0}
                width={innerW}
                height={innerH}
                fill="transparent"
                onPointerMove={onMove}
                onPointerLeave={() => setHover(null)}
              />
            </g>
          </svg>
        )}
        <div className="chart-legend" style={{ bottom: margin.bottom - 2 }}>
          <span>
            <span className="swatch" style={{ background: CLEAN }} />
            Tagesenergie
          </span>
          <span>
            <span className="line-swatch" style={{ background: LINE }} />
            Mittlere Windgeschwindigkeit (m/s)
          </span>
        </div>
        {hovered && (
          <ChartTooltip left={hover!.left} top={hover!.top} width={width}>
            <DailyTooltipContent point={hovered} />
          </ChartTooltip>
        )}
      </div>
    </div>
  );
});

function DailyTooltipContent({ point }: { point: DailyPoint }) {
  return (
    <>
      <div className="tooltip-title">{new Date(point.day).toLocaleDateString("de-DE")}</div>
      <div>
        Energie: <strong>{asMWh(point.energy_kwh)} MWh</strong>
      </div>
      <div>
        Mittlerer Wind: {asMs(point.mean_wind_ms)} m/s
        {point.max_wind_ms != null && ` · max ${asMs(point.max_wind_ms)} m/s`}
      </div>
    </>
  );
}
