/** Daily chart — ComposedChart: bars = daily energy (MWh) with per-bar coloring
 * via Cell (clean → accent, no ok hours → gap), line = mean wind (m/s) on the
 * second y-axis; tooltip shows ok hours. Title and range switcher live in
 * App's panel head. QC tracking moved to the wind panel (plan 2026-10-27). */
import { memo } from "react";
import {
  Bar,
  CartesianGrid,
  Cell,
  ComposedChart,
  Legend,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import type { DailyPoint } from "../api";
import { useAnimateOnce } from "../useAnimateOnce";
import { asHours, asMs, asMWh } from "../format";

const CLEAN = "#3b82f6";
const GAP = "#e5e7eb";

const barColor = (point: DailyPoint): string =>
  point.energy_kwh == null ? GAP : CLEAN;

/** Memoized: per-panel data references stay stable across unchanged polls,
 * so a metrics-only tick never reconciles the (up to 365-point) chart. */
export const DailyChart = memo(function DailyChart({ daily }: { daily: DailyPoint[] }) {
  const animate = useAnimateOnce();

  const chartData = daily.map((point) => ({
    ...point,
    energy_mwh: point.energy_kwh == null ? null : point.energy_kwh / 1000,
  }));

  return (
    <div className="chart">
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={chartData}>
          <CartesianGrid strokeDasharray="3 3" />
          <XAxis dataKey="day" tickFormatter={(day: string) => day.slice(5)} minTickGap={24} />
          <YAxis yAxisId="energy" tickFormatter={(mwh: number) => mwh.toFixed(0)} />
          <YAxis yAxisId="wind" orientation="right" width={40} />
          <Tooltip content={<DailyTooltip />} />
          <Legend />
          <Bar
            yAxisId="energy"
            dataKey="energy_mwh"
            name="Tagesenergie"
            isAnimationActive={animate}
          >
            {daily.map((point) => (
              <Cell key={point.day} fill={barColor(point)} />
            ))}
          </Bar>
          <Line
            yAxisId="wind"
            dataKey="mean_wind_ms"
            name="Mittlere Windgeschwindigkeit (m/s)"
            stroke="#b45309"
            dot={false}
            isAnimationActive={animate}
          />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
});

function DailyTooltip({
  active,
  payload,
}: {
  active?: boolean;
  payload?: { payload: DailyPoint }[];
}) {
  if (!active) return null;
  const point = payload?.[0]?.payload;
  if (!point) return null;

  return (
    <div className="tooltip">
      <div className="tooltip-title">{new Date(point.day).toLocaleDateString("de-DE")}</div>
      <div>
        Energie: <strong>{asMWh(point.energy_kwh)} MWh</strong>
      </div>
      <div>
        Mittlerer Wind: {asMs(point.mean_wind_ms)} m/s
        {point.max_wind_ms != null && ` · max ${asMs(point.max_wind_ms)} m/s`}
      </div>
      <div>Verwertbare Stunden: {asHours(point.hours)}/24</div>
    </div>
  );
}
