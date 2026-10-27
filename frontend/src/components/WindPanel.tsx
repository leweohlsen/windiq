/** Wind panel — wind rose as a compact summary on top, speed chart as the
 * main view below. Drag the brush strip under the speed chart to zoom into
 * a sub-range (Chrome DevTools Network-tab style). The DB only holds valid
 * values; interpolated hours appear as amber dots with their reason in the
 * tooltip (qc_note from the ingest pipeline).
 *
 * Charts are hand-rolled SVG via visx primitives (see chart/helpers.ts):
 * whole series render as single path elements (computed once per data
 * change), and hover resolves to an index by scale inversion, so pointer
 * handling stays O(log n) even at a full year of hourly buckets. */
import { memo, useMemo, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";
import { AxisBottom, AxisLeft } from "@visx/axis";
import { scaleLinear } from "@visx/scale";
import { area as d3Area, curveMonotoneX, line as d3Line } from "@visx/vendor/d3-shape";

import type { RoseSector, WindPoint, WindResponse } from "../api";
import { asBucket, asHours, asMs } from "../format";
import { CHART, axisProps } from "./chart/theme";
import { ChartTooltip } from "./chart/ChartTooltip";
import { clampIndex, polarPoint, strideTicks } from "./chart/helpers";
import { useChartSize } from "./chart/useChartSize";
import { BrushStrip } from "./BrushStrip";

/** Rose rings sit on the violet fill, so they need to read against it. */
const ROSE_RING = "#e2e8f0";
/** Whole-year hourly series render fine; above this, per-point dot markers
 * stop being distinguishable anyway. */
const DOT_LIMIT = 1_000;

type Hover = { idx: number; left: number; top: number };

/* Compass order N → NNW, i.e. clockwise, matching the server's 16 sectors. */
const COMPASS = [
  "N",
  "NNE",
  "NE",
  "ENE",
  "E",
  "ESE",
  "SE",
  "SSE",
  "S",
  "SSW",
  "SW",
  "WSW",
  "W",
  "WNW",
  "NW",
  "NNW",
];
const COMPASS_STEP = 360 / COMPASS.length;

/** Memoized: per-panel data references stay stable across unchanged polls,
 * so a metrics-only tick never reconciles either chart. */
export const WindPanel = memo(function WindPanel({ wind }: { wind: WindResponse }) {
  const [zoomDomain, setZoomDomain] = useState<[string, string] | null>(null);

  const filteredSeries = useMemo(() => {
    if (!zoomDomain) return wind.series;
    const [start, end] = zoomDomain;
    return wind.series.filter((p) => p.timestamp >= start && p.timestamp <= end);
  }, [wind.series, zoomDomain]);

  return (
    <>
      <div className="wind-panel-row">
        <div className="chart chart-rose">
          <WindRose rose={wind.rose} />
        </div>
        <div className="chart-column">
          <div className="chart chart-speed">
            <WindSpeedChart series={filteredSeries} resolution={wind.resolution} />
          </div>
          <div className="brush-row">
            <BrushStrip data={wind.series} zoomDomain={zoomDomain} onZoomChange={setZoomDomain} />
            {zoomDomain && (
              <button className="reset-zoom" onClick={() => setZoomDomain(null)}>
                ×
              </button>
            )}
          </div>
        </div>
      </div>
    </>
  );
});

/* Rose column layout — Bearings are index-derived over the full circle so
 * each spoke lands on its exact compass bearing; the numeric angle maps
 * 0° → top and runs clockwise. */
function WindRose({ rose }: { rose: RoseSector[] }) {
  const { ref, width, height } = useChartSize();
  const svgRef = useRef<SVGSVGElement>(null);
  const [hover, setHover] = useState<Hover | null>(null);

  const cx = width / 2;
  const cy = height / 2;
  const outer = (Math.min(width, height) / 2) * 0.75;
  const maxFreq = Math.max(1, ...rose.map((s) => s.frequency));
  const radius = (v: number) => (v / maxFreq) * outer;

  const onMove = (e: ReactPointerEvent) => {
    const rect = svgRef.current?.getBoundingClientRect();
    if (!rect) return;
    const left = e.clientX - rect.left;
    const top = e.clientY - rect.top;
    const deg = ((Math.atan2(left - cx, -(top - cy)) * 180) / Math.PI + 360) % 360;
    setHover({
      idx: clampIndex(Math.round(deg / COMPASS_STEP), COMPASS.length),
      left,
      top,
    });
  };

  /* Rings at quarter fractions of the outer radius, spokes per sector. */
  const rings = [0.25, 0.5, 0.75, 1];
  const polygon = rose
    .map((sector, i) => polarPoint(cx, cy, radius(sector.frequency), i * COMPASS_STEP))
    .map((p) => `${p.x.toFixed(1)},${p.y.toFixed(1)}`)
    .join(" ");

  return (
    <div ref={ref} className="chart-inner">
      {width > 0 && (
        <svg
          ref={svgRef}
          width={width}
          height={height}
          onPointerMove={onMove}
          onPointerLeave={() => setHover(null)}
        >
          <defs>
            <linearGradient id="rose-fill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={CHART.violet} stopOpacity={0.45} />
              <stop offset="100%" stopColor={CHART.violet} stopOpacity={0.12} />
            </linearGradient>
          </defs>
          {rings.map((frac) => (
            <circle
              key={frac}
              cx={cx}
              cy={cy}
              r={outer * frac}
              fill="none"
              stroke={ROSE_RING}
            />
          ))}
          {rose.map((_, i) => {
            const deg = i * COMPASS_STEP;
            const tip = polarPoint(cx, cy, outer, deg);
            const isHover = hover?.idx === i;
            return (
              <line
                key={i}
                x1={cx}
                y1={cy}
                x2={tip.x}
                y2={tip.y}
                stroke={isHover ? CHART.violet : ROSE_RING}
                strokeWidth={isHover ? 1.5 : 1}
              />
            );
          })}
          {rose.length > 0 && (
            <polygon
              points={polygon}
              fill="url(#rose-fill)"
              stroke={CHART.violet}
              strokeWidth={2}
              strokeLinejoin="round"
            />
          )}
          {rose.map((_, i) => {
            const deg = i * COMPASS_STEP;
            const p = polarPoint(cx, cy, outer + 13, deg);
            const isHover = hover?.idx === i;
            return (
              <text
                key={deg}
                x={p.x}
                y={p.y}
                textAnchor={deg === 0 || deg === 180 ? "middle" : deg < 180 ? "start" : "end"}
                fontSize={11}
                fontWeight={isHover ? 600 : 500}
                fill={isHover ? CHART.violet : CHART.marker}
                dy={deg === 0 ? -1 : deg === 180 ? 8 : 3.5}
              >
                {COMPASS[i]}
              </text>
            );
          })}
        </svg>
      )}
      {hover && width > 0 && rose[hover.idx] && (
        <ChartTooltip left={hover.left} top={hover.top} width={width}>
          <RoseTooltipContent sector={rose[hover.idx]!} />
        </ChartTooltip>
      )}
    </div>
  );
}

function WindSpeedChart({
  series,
  resolution,
}: {
  series: WindPoint[];
  resolution: WindResponse["resolution"];
}) {
  const { ref, width, height } = useChartSize();
  const svgRef = useRef<SVGSVGElement>(null);
  const [hover, setHover] = useState<Hover | null>(null);

  const margin = { top: 12, right: 12, bottom: 28, left: 40 };
  const innerW = Math.max(0, width - margin.left - margin.right);
  const innerH = Math.max(0, height - margin.top - margin.bottom);

  const n = series.length;
  const xScale = useMemo(
    () => scaleLinear({ domain: [0, Math.max(0, n - 1)], range: [0, innerW] }),
    [n, innerW],
  );

  /* Min/max band and mean set the y-extent; recharts drew the same auto domain. */
  const yMax = Math.max(
    1,
    ...series.map((p) => p.max_wind_ms ?? p.mean_wind_ms ?? 0),
    ...series.map((p) => p.mean_wind_ms ?? 0),
  );
  const yScale = useMemo(() => {
    const s = scaleLinear({ domain: [0, yMax], range: [innerH, 0] });
    return s.nice();
  }, [yMax, innerH]);

  const xTicks = useMemo(
    () => strideTicks(n, innerW, resolution === "hour" ? 95 : 70),
    [n, innerW, resolution],
  );

  const bandPath = useMemo(
    () =>
      d3Area<WindPoint>()
        .curve(curveMonotoneX)
        .defined((p) => p.min_wind_ms != null && p.max_wind_ms != null)
        .x((_p, i) => xScale(i))
        .y0((p) => yScale(p.min_wind_ms!))
        .y1((p) => yScale(p.max_wind_ms!))(series) ?? "",
    [xScale, yScale, series],
  );
  const meanPath = useMemo(
    () =>
      d3Line<WindPoint>()
        .curve(curveMonotoneX)
        .defined((p) => p.mean_wind_ms != null)
        .x((_p, i) => xScale(i))
        .y((p) => yScale(p.mean_wind_ms!))(series) ?? "",
    [xScale, yScale, series],
  );

  const ready = width > 0 && n > 0;

  const onMove = (e: ReactPointerEvent) => {
    const rect = svgRef.current?.getBoundingClientRect();
    if (!rect) return;
    const px = e.clientX - rect.left - margin.left;
    if (px < -10 || px > innerW + 10) {
      setHover(null);
      return;
    }
    const idx = clampIndex(xScale.invert(px), n);
    const point = series[idx]!;
    /* Anchor the box above the min/max band when present, else the mean. */
    const anchor = point.max_wind_ms ?? point.mean_wind_ms ?? yMax;
    setHover({ idx, left: xScale(idx) + margin.left, top: yScale(anchor) + margin.top });
  };

  const hovered = hover != null ? (series[hover.idx] ?? null) : null;
  const interpDots: { i: number; y: number; ts: string }[] =
    n <= DOT_LIMIT
      ? series.flatMap((p, i) =>
          p.interpolated_hours > 0 && p.mean_wind_ms != null
            ? [{ i, y: yScale(p.mean_wind_ms), ts: p.timestamp }]
            : [],
        )
      : [];

  return (
    <div ref={ref} className="chart-inner">
      {ready && (
        <svg ref={svgRef} width={width} height={height}>
          <defs>
            <linearGradient id="speed-band-fill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={CHART.violet} stopOpacity={0.22} />
              <stop offset="100%" stopColor={CHART.violet} stopOpacity={0.04} />
            </linearGradient>
          </defs>
          <g transform={`translate(${margin.left},${margin.top})`}>
            {yScale.ticks(4).map((t) => (
              <line
                key={`h${t}`}
                x1={0}
                x2={innerW}
                y1={yScale(t)}
                y2={yScale(t)}
                stroke={CHART.grid}
              />
            ))}
            <path d={bandPath} fill="url(#speed-band-fill)" stroke="none" />
            <path
              d={meanPath}
              fill="none"
              stroke={CHART.violet}
              strokeWidth={2}
              strokeLinecap="round"
              strokeLinejoin="round"
            />
            {interpDots.map(({ i, y, ts }) => (
              <circle
                key={ts}
                cx={xScale(i)}
                cy={y}
                r={3.5}
                fill={CHART.amber}
                stroke="#fff"
                strokeWidth={1.5}
              />
            ))}
            <AxisBottom
              top={innerH}
              scale={xScale}
              tickValues={xTicks}
              tickFormat={(v) => asBucket(series[Number(v)]?.timestamp ?? "", resolution)}
              {...axisProps}
            />
            <AxisLeft
              scale={yScale}
              tickFormat={(v) => Number(v).toFixed(0)}
              {...axisProps}
            />
            {hover && (
              <g pointerEvents="none">
                <line
                  x1={xScale(hover.idx)}
                  x2={xScale(hover.idx)}
                  y1={0}
                  y2={innerH}
                  stroke={CHART.hover}
                  strokeDasharray="3 4"
                  opacity={0.6}
                />
                {hovered?.mean_wind_ms != null && (
                  <circle
                    cx={xScale(hover.idx)}
                    cy={yScale(hovered.mean_wind_ms)}
                    r={4}
                    fill={CHART.violet}
                    stroke="#fff"
                    strokeWidth={1.5}
                  />
                )}
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
      {hovered && (
        <ChartTooltip left={hover!.left} top={hover!.top} width={width}>
          <SpeedTooltipContent point={hovered} resolution={resolution} />
        </ChartTooltip>
      )}
    </div>
  );
}

function RoseTooltipContent({ sector }: { sector: RoseSector }) {
  return (
    <>
      <div className="tooltip-title">
        {sector.direction} ({sector.degrees}°)
      </div>
      <div>
        Verwertbare Stunden: <strong>{asHours(sector.frequency)}</strong>
      </div>
      <div>Mittlere Geschwindigkeit: {asMs(sector.mean_speed_ms)} m/s</div>
    </>
  );
}

function SpeedTooltipContent({
  point,
  resolution,
}: {
  point: WindPoint;
  resolution: WindResponse["resolution"];
}) {
  return (
    <>
      <div className="tooltip-title">{asBucket(point.timestamp, resolution)}</div>
      <div>
        Mittel: <strong>{asMs(point.mean_wind_ms)} m/s</strong>
      </div>
      <div>
        Min / Max: {asMs(point.min_wind_ms)} / {asMs(point.max_wind_ms)} m/s
      </div>
      {point.interpolated_hours > 0 && (
        <div className="interp-note">
          {asHours(point.interpolated_hours)} h interpoliert
          {point.qc_note ? ` (${point.qc_note})` : ""}
          {point.wind_speed_raw ? ` · Original: ${point.wind_speed_raw}` : ""}
        </div>
      )}
    </>
  );
}
