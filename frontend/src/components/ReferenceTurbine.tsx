/** ReferenceTurbine — spec cards plus the power curve (Wirkungskurve) from
 * /api/turbine; swept area and specific power are derived from the specs.
 *
 * The chart is hand-rolled SVG via visx primitives (see chart/helpers.ts):
 * monotone area + line path, numeric axes with the same round tick steps as
 * before, and the rated/cut-in/cut-out reference markers as plain lines. */
import { memo, useMemo, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";
import { AxisBottom, AxisLeft } from "@visx/axis";
import { scaleLinear } from "@visx/scale";
import { area as d3Area, curveMonotoneX, line as d3Line } from "@visx/vendor/d3-shape";

import type { PowerCurvePoint, TurbineDetail } from "../api";
import { asNum } from "../format";
import { ChartTooltip } from "./chart/ChartTooltip";
import { clampIndex } from "./chart/helpers";
import { useChartSize } from "./chart/useChartSize";

const LINE = "#3b82f6";
const MUTED = "#6b7280";
const GRID = "#e4e8ef";

const margin = { top: 20, right: 12, bottom: 26, left: 48 };

type Hover = { idx: number; left: number; top: number };

export const ReferenceTurbine = memo(function ReferenceTurbine({
  turbine,
}: {
  turbine: TurbineDetail;
}) {
  const { ref, width, height } = useChartSize();
  const svgRef = useRef<SVGSVGElement>(null);
  const [hover, setHover] = useState<Hover | null>(null);

  const sweptAreaM2 = (Math.PI / 4) * turbine.rotor_diameter_m ** 2;
  const specificPowerWm2 = (turbine.rated_power_kw * 1000) / sweptAreaM2;

  const curve = turbine.power_curve;
  const n = curve.length;

  const innerW = Math.max(0, width - margin.left - margin.right);
  const innerH = Math.max(0, height - margin.top - margin.bottom);

  const maxSpeed = curve.at(-1)?.wind_speed_ms ?? turbine.cut_out_wind_speed_ms;
  const xScale = useMemo(
    () => scaleLinear({ domain: [0, maxSpeed], range: [0, innerW] }),
    [maxSpeed, innerW],
  );
  const yMax = Math.ceil(turbine.rated_power_kw / 1000) * 1000;
  const yScale = useMemo(
    () => scaleLinear({ domain: [0, yMax], range: [innerH, 0] }),
    [yMax, innerH],
  );

  const areaPath = useMemo(
    () =>
      d3Area<PowerCurvePoint>()
        .curve(curveMonotoneX)
        .x((p) => xScale(p.wind_speed_ms))
        .y0(yScale(0))
        .y1((p) => yScale(p.power_kw))(curve) ?? "",
    [xScale, yScale, curve],
  );
  const linePath = useMemo(
    () =>
      d3Line<PowerCurvePoint>()
        .curve(curveMonotoneX)
        .x((p) => xScale(p.wind_speed_ms))
        .y((p) => yScale(p.power_kw))(curve) ?? "",
    [xScale, yScale, curve],
  );

  const hovered = hover != null ? (curve[hover.idx] ?? null) : null;

  return (
    <>
      <div className="charts-row">
        <div className="cards">
          <Spec label="Nennleistung" value={`${asNum(turbine.rated_power_kw, 0)} kW`} />
          <Spec label="Nabenhöhe" value={`${asNum(turbine.hub_height_m, 0)} m`} />
          <Spec label="Rotordurchmesser" value={`${asNum(turbine.rotor_diameter_m, 0)} m`} />
          <Spec label="Überstrichene Fläche" value={`${asNum(sweptAreaM2, 0)} m²`} />
          <Spec label="Spezifische Leistung" value={`${asNum(specificPowerWm2, 0)} W/m²`} />
          <Spec
            label="Cut-in / Cut-out"
            value={`${asNum(turbine.cut_in_wind_speed_ms, 1)} / ${asNum(turbine.cut_out_wind_speed_ms, 1)} m/s`}
          />
        </div>

        <div>
          <h3 className="chart-title">Leistungskurve (Wirkungskurve)</h3>
          <div className="chart">
            <div ref={ref} className="chart-inner">
              {width > 0 && n > 0 && (
                <svg ref={svgRef} width={width} height={height}>
                  <defs>
                    <linearGradient id="power-curve-fill" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor={LINE} stopOpacity={0.35} />
                      <stop offset="100%" stopColor={LINE} stopOpacity={0.02} />
                    </linearGradient>
                  </defs>
                  <g transform={`translate(${margin.left},${margin.top})`}>
                    <g>
                      {yScale.ticks(5).map((t) => (
                        <line
                          key={t}
                          x1={0}
                          x2={innerW}
                          y1={yScale(t)}
                          y2={yScale(t)}
                          stroke={GRID}
                          strokeDasharray="3 3"
                        />
                      ))}
                    </g>
                    <line
                      x1={0}
                      x2={innerW}
                      y1={yScale(turbine.rated_power_kw)}
                      y2={yScale(turbine.rated_power_kw)}
                      stroke={MUTED}
                      strokeDasharray="4 4"
                    />
                    <text
                      x={innerW - 4}
                      y={yScale(turbine.rated_power_kw) - 6}
                      textAnchor="end"
                      fontSize={11}
                      fill={MUTED}
                    >
                      Nennleistung {asNum(turbine.rated_power_kw, 0)} kW
                    </text>
                    <line
                      x1={xScale(turbine.cut_in_wind_speed_ms)}
                      x2={xScale(turbine.cut_in_wind_speed_ms)}
                      y1={0}
                      y2={innerH}
                      stroke={MUTED}
                      strokeDasharray="4 4"
                    />
                    <text
                      x={xScale(turbine.cut_in_wind_speed_ms) + 4}
                      y={10}
                      fontSize={11}
                      fill={MUTED}
                    >
                      Cut-in {asNum(turbine.cut_in_wind_speed_ms, 1)}
                    </text>
                    <line
                      x1={xScale(turbine.cut_out_wind_speed_ms)}
                      x2={xScale(turbine.cut_out_wind_speed_ms)}
                      y1={0}
                      y2={innerH}
                      stroke={MUTED}
                      strokeDasharray="4 4"
                    />
                    <text
                      x={xScale(turbine.cut_out_wind_speed_ms) - 4}
                      y={innerH - 5}
                      textAnchor="end"
                      fontSize={11}
                      fill={MUTED}
                    >
                      Cut-out {asNum(turbine.cut_out_wind_speed_ms, 1)}
                    </text>
                    <path d={areaPath} fill="url(#power-curve-fill)" stroke="none" />
                    <path d={linePath} fill="none" stroke={LINE} strokeWidth={2} />
                    <AxisBottom
                      top={innerH}
                      scale={xScale}
                      tickValues={xTicks(turbine)}
                      tickFormat={(v) => Number(v).toFixed(0)}
                      tickLength={4}
                      stroke={GRID}
                      tickStroke={GRID}
                      tickLabelProps={{ fill: MUTED, fontFamily: "inherit", fontSize: 11 }}
                    />
                    <AxisLeft
                      scale={yScale}
                      tickFormat={(v) => Number(v).toFixed(0)}
                      tickLength={4}
                      stroke={GRID}
                      tickStroke={GRID}
                      tickLabelProps={{ fill: MUTED, fontFamily: "inherit", fontSize: 11 }}
                    />
                    {hover && hovered && (
                      <g pointerEvents="none">
                        <line
                          x1={xScale(hovered.wind_speed_ms)}
                          x2={xScale(hovered.wind_speed_ms)}
                          y1={0}
                          y2={innerH}
                          stroke={MUTED}
                          strokeDasharray="3 3"
                          opacity={0.5}
                        />
                        <circle
                          cx={xScale(hovered.wind_speed_ms)}
                          cy={yScale(hovered.power_kw)}
                          r={4}
                          fill={LINE}
                          stroke="#fff"
                          strokeWidth={1.5}
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
              {hovered && (
                <ChartTooltip left={hover!.left} top={hover!.top} width={width}>
                  <CurveTooltipContent point={hovered} />
                </ChartTooltip>
              )}
            </div>
          </div>
          <p className="chart-note">Windgeschwindigkeit (m/s) → Leistung (kW), 1-m/s-Schritte</p>
        </div>
      </div>
    </>
  );

  function onMove(e: ReactPointerEvent) {
    const rect = svgRef.current?.getBoundingClientRect();
    if (!rect) return;
    const px = e.clientX - rect.left - margin.left;
    if (px < -10 || px > innerW + 10) {
      setHover(null);
      return;
    }
    /* Curve points sit at 1-m/s steps, so the inverted speed *is* the index. */
    const idx = clampIndex(xScale.invert(px), n);
    const point = curve[idx]!;
    setHover({
      idx,
      left: xScale(point.wind_speed_ms) + margin.left,
      top: yScale(point.power_kw) + margin.top,
    });
  }
});

/** Round x-axis ticks (0/5/10/… m/s) instead of one tick per curve point. */
function xTicks(turbine: TurbineDetail): number[] {
  const max = turbine.power_curve.at(-1)?.wind_speed_ms ?? turbine.cut_out_wind_speed_ms;
  const step = max > 20 ? 5 : max > 10 ? 2 : 1;
  return Array.from({ length: Math.floor(max / step) + 1 }, (_, i) => i * step);
}

function Spec({ label, value }: { label: string; value: string }) {
  return (
    <div className="card">
      <span className="label">{label}</span>
      <span className="value small">{value}</span>
    </div>
  );
}

function CurveTooltipContent({ point }: { point: PowerCurvePoint }) {
  return (
    <>
      <div className="tooltip-title">{asNum(point.wind_speed_ms, 1)} m/s Wind</div>
      <div>
        Leistung: <strong>{asNum(point.power_kw, 0)} kW</strong>
      </div>
    </>
  );
}
