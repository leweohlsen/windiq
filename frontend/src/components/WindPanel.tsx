/** Wind panel — wind rose as a compact summary on top, speed chart as the
 * main view below. Drag the brush strip under the speed chart to zoom into
 * a sub-range (Chrome DevTools Network-tab style). QC info lives in the
 * tooltip, not as stacked bars on the chart. */
import { memo, useMemo, useState } from "react";
import {
  Area,
  CartesianGrid,
  ComposedChart,
  Line,
  PolarAngleAxis,
  PolarGrid,
  PolarRadiusAxis,
  Radar,
  RadarChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import type { RoseSector, WindPoint, WindResponse } from "../api";
import { useAnimateOnce } from "../useAnimateOnce";
import { asBucket, asHours, asMs } from "../format";
import type { ComponentProps } from "react";
import { BrushStrip } from "./BrushStrip";

const LINE = "#b45309";
const QC_BAD = "#b91c1c"; // missing + malformed
const QC_FAULTY = "#b45309"; // suspect

/* Compass order N → NNW, i.e. clockwise, matching the server's 16 sectors. */
const COMPASS = [
  "N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
  "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW",
];
const COMPASS_STEP = 360 / COMPASS.length;
const COMPASS_TICKS = COMPASS.map((_, i) => i * COMPASS_STEP);

/** Memoized: per-panel data references stay stable across unchanged polls,
 * so a metrics-only tick never reconciles either chart. */
export const WindPanel = memo(function WindPanel({ wind }: { wind: WindResponse }) {
  const animate = useAnimateOnce();
  const [zoomDomain, setZoomDomain] = useState<[string, string] | null>(null);

  /* Bearings are index-derived over the full circle: the numeric angle axis
   * maps 0° → top and runs clockwise, so each spoke lands on its exact
   * compass bearing (a category axis would sit spokes off-center on a d3
   * band scale; server degrees are truncated to integers). */
  const rose = wind.rose.map((sector, i) => ({
    ...sector,
    bearing: i * COMPASS_STEP,
  }));
  const maxFreq = Math.max(1, ...rose.map((s) => s.frequency));

  const filteredSeries = useMemo(() => {
    if (!zoomDomain) return wind.series;
    const [start, end] = zoomDomain;
    return wind.series.filter((p) => p.timestamp >= start && p.timestamp <= end);
  }, [wind.series, zoomDomain]);

  return (
    <>
      <div className="wind-panel-row">
        <div className="chart chart-rose">
          <ResponsiveContainer width="100%" height="100%">
            <RadarChart data={rose} startAngle={90} endAngle={-270} outerRadius="75%">
              <PolarGrid gridType="circle" />
              <PolarAngleAxis
                dataKey="bearing"
                type="number"
                domain={[0, 360]}
                ticks={COMPASS_TICKS as unknown as ComponentProps<typeof PolarAngleAxis>["ticks"]}
                tickFormatter={(deg: number) =>
                  COMPASS[Math.round(deg / COMPASS_STEP) % COMPASS.length] ?? "N"
                }
              />
              <PolarRadiusAxis domain={[0, maxFreq]} tick={false} axisLine={false} />
              <Radar
                dataKey="frequency"
                stroke={LINE}
                fill={LINE}
                fillOpacity={0.4}
                isAnimationActive={animate}
              />
              <Tooltip content={<RoseTooltip />} />
            </RadarChart>
          </ResponsiveContainer>
        </div>
        <div className="chart-column">
          <div className="chart chart-speed">
            <ResponsiveContainer width="100%" height="100%">
              <ComposedChart data={filteredSeries}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis
                  dataKey="timestamp"
                  tickFormatter={(ts: string) => asBucket(ts, wind.resolution)}
                  minTickGap={28}
                />
                <YAxis width={40} tickFormatter={(v: number) => v.toFixed(0)} />
                <Tooltip content={<SpeedTooltip resolution={wind.resolution} />} />
                <Area
                  dataKey={(p: WindPoint) =>
                    p.min_wind_ms != null && p.max_wind_ms != null
                      ? [p.min_wind_ms, p.max_wind_ms]
                      : null
                  }
                  fill={LINE}
                  fillOpacity={0.15}
                  stroke="none"
                  isAnimationActive={animate}
                  name="Min/Max (Originalwerte)"
                  legendType="none"
                />
                <Line
                  dataKey="mean_wind_ms"
                  name="Mittel (m/s)"
                  stroke={LINE}
                  dot={qcDot}
                  isAnimationActive={animate}
                />
              </ComposedChart>
            </ResponsiveContainer>
          </div>
          <div className="brush-row">
            <BrushStrip
              data={wind.series}
              zoomDomain={zoomDomain}
              onZoomChange={setZoomDomain}
            />
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

/** Per-point QC marker on the speed chart. Missing wins over malformed wins
 * over suspect — the worst issue in the bucket drives the color/shape. */
function qcDot(props: { cx?: number; cy?: number; payload?: WindPoint }) {
  const { cx, cy, payload } = props;
  if (cx == null || cy == null || !payload) return null;
  if (payload.mean_wind_ms == null || payload.missing_hours > 0) {
    return <circle cx={cx} cy={cy} r={3.5} fill={QC_BAD} stroke="#fff" strokeWidth={1} />;
  }
  if (payload.malformed_hours > 0) {
    return <rect x={cx - 3} y={cy - 3} width={6} height={6} fill={QC_BAD} stroke="#fff" strokeWidth={1} />;
  }
  if (payload.suspect_hours > 0) {
    return <circle cx={cx} cy={cy} r={3} fill={QC_FAULTY} stroke="#fff" strokeWidth={1} />;
  }
  return null;
}

function RoseTooltip({
  active,
  payload,
}: {
  active?: boolean;
  payload?: { payload: RoseSector }[];
}) {
  if (!active) return null;
  const sector = payload?.[0]?.payload;
  if (!sector) return null;
  return (
    <div className="tooltip">
      <div className="tooltip-title">
        {sector.direction} ({sector.degrees}°)
      </div>
      <div>
        Verwertbare Stunden: <strong>{asHours(sector.frequency)}</strong>
      </div>
      <div>Mittlere Geschwindigkeit: {asMs(sector.mean_speed_ms)} m/s</div>
    </div>
  );
}

function SpeedTooltip({
  active,
  payload,
  resolution,
}: {
  active?: boolean;
  payload?: { payload: WindPoint }[];
  resolution: "hour" | "day" | "week";
}) {
  if (!active) return null;
  const point = payload?.[0]?.payload;
  if (!point) return null;
  return (
    <div className="tooltip">
      <div className="tooltip-title">{asBucket(point.timestamp, resolution)}</div>
      <div>
        Mittel: <strong>{asMs(point.mean_wind_ms)} m/s</strong>
      </div>
      <div>
        Min / Max (Originalwerte): {asMs(point.min_wind_ms)} / {asMs(point.max_wind_ms)} m/s
      </div>
      <div>
        QC: {point.suspect_hours} verdächtig · {point.missing_hours} ohne Wert ·{" "}
        {point.malformed_hours} fehlerhaft
      </div>
    </div>
  );
}
