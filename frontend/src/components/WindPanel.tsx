/** Wind panel — wind rose as polar RadarChart over the 16 server-computed
 * sectors (frequency encoded in radius, ok-hours tooltip) plus a plain 48 h
 * speed line; direction appears only in the rose (plan phase 4). */
import {
  CartesianGrid,
  Line,
  LineChart,
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

import type { RoseSector, WindResponse } from "../api";
import { asClock, asHours, asMs } from "../format";
import type { ComponentProps } from "react";

const BAR = "#3b82f6";
const LINE = "#b45309";

/* Compass order N → NNW, i.e. clockwise, matching the server's 16 sectors. */
const COMPASS = [
  "N", "NNE", "NE", "ENE",
  "E", "ESE", "SE", "SSE",
  "S", "SSW", "SW", "WSW",
  "W", "WNW", "NW", "NNW",
];
const COMPASS_STEP = 360 / COMPASS.length;
const COMPASS_TICKS = COMPASS.map((_, i) => i * COMPASS_STEP);

export function WindPanel({ wind }: { wind: WindResponse }) {
  const series = wind.series.map((point) => ({
    timestamp: point.timestamp,
    wind_speed_ms: point.wind_speed_ms,
  }));

  /* Bearings are index-derived over the full circle: the numeric angle axis
   * maps 0° → top and runs clockwise, so each spoke lands on its exact
   * compass bearing (a category axis would sit spokes off-center on a d3
   * band scale; server degrees are truncated to integers). */
  const rose = wind.rose.map((sector, i) => ({
    ...sector,
    bearing: i * COMPASS_STEP,
  }));
  const maxFreq = Math.max(1, ...rose.map((s) => s.frequency));

  return (
    <>
      <div className="charts-row">
        <div>
          <h3 className="chart-title">
            Windrose — {asHours(wind.rose.reduce((n, s) => n + s.frequency, 0))}{" "}
            verwertbare Stunden · letzte 30 Tage
          </h3>
          <div className="chart chart-rose">
            <ResponsiveContainer width="100%" height="100%">
              <RadarChart data={rose} startAngle={90} endAngle={-270} outerRadius="75%">
                <PolarGrid gridType="circle" />
                <PolarAngleAxis
                  dataKey="bearing"
                  type="number"
                  domain={[0, 360]}
                  ticks={COMPASS_TICKS as unknown as ComponentProps<typeof PolarAngleAxis>["ticks"]}
                  tickFormatter={(deg: number) => COMPASS[Math.round(deg / COMPASS_STEP) % 16]}
                />
                <PolarRadiusAxis domain={[0, maxFreq]} tick={false} axisLine={false} />
                <Radar dataKey="frequency" stroke={BAR} fill={BAR} fillOpacity={0.4} />
                <Tooltip content={<RoseTooltip />} />
              </RadarChart>
            </ResponsiveContainer>
            <p className="chart-note">0° N · 90° E · 180° S · 270° W (im Uhrzeigersinn)</p>
          </div>
        </div>
        <div>
          <h3 className="chart-title">
            Windgeschwindigkeit — letzte {wind.hours} h (Messhöhe)
          </h3>
          <div className="chart">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={series}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis
                  dataKey="timestamp"
                  tickFormatter={(ts: string) =>
                    new Date(ts).toLocaleString("de-DE", {
                      month: "short",
                      day: "numeric",
                      hour: "2-digit",
                      minute: "2-digit",
                      hour12: false,
                    })
                  }
                  minTickGap={28}
                />
                <YAxis width={40} tickFormatter={(v: number) => v.toFixed(0)} />
                <Tooltip content={<SpeedTooltip />} />
                <Line
                  dataKey="wind_speed_ms"
                  name="Windgeschwindigkeit (m/s)"
                  stroke={LINE}
                  dot={false}
                />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>
      </div>
    </>
  );
}

function RoseTooltip({
  active,
  payload,
}: {
  active?: boolean;
  payload?: { payload: RoseSector }[];
}) {
  if (!active || !payload || payload.length === 0) return null;
  const sector = payload[0].payload;
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
}: {
  active?: boolean;
  payload?: { payload: { timestamp: string; wind_speed_ms: number } }[];
}) {
  if (!active || !payload || payload.length === 0) return null;
  const point = payload[0].payload;
  return (
    <div className="tooltip">
      <div className="tooltip-title">{asClock(point.timestamp)}</div>
      <div>
        Windgeschwindigkeit: <strong>{asMs(point.wind_speed_ms)} m/s</strong>
      </div>
    </div>
  );
}
