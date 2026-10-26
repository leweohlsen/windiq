/** Daily chart — ComposedChart: bars = daily energy (MWh) with per-bar QC
 * coloring via Cell (clean → accent, suspect hours → amber, no ok hours →
 * gap), line = mean wind (m/s) on the second y-axis; tooltip shows ok hours +
 * QC counts; range switcher 30/90/365 days (plan phase 4). */
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
import { DAILY_RANGES } from "../useDashboard";
import { asHours, asMs, asMWh } from "../format";

const CLEAN = "#3b82f6";
const SUSPECT = "#f59e0b";
const GAP = "#e5e7eb";

const barColor = (point: DailyPoint): string => {
  if (point.energy_kwh == null) return GAP;
  if (point.suspect_hours > 0) return SUSPECT;
  return CLEAN;
};

export function DailyChart({
  daily,
  days,
  onRangeChange,
}: {
  daily: DailyPoint[];
  days: number;
  onRangeChange: (days: number) => void;
}) {
  const chartData = daily.map((point) => ({
    ...point,
    energy_mwh: point.energy_kwh == null ? null : point.energy_kwh / 1000,
  }));

  return (
    <>
      <div className="panel-head">
        <h2>Tagesenergie ({days} Tage)</h2>
        <div className="range-switch">
          {DAILY_RANGES.map((range) => (
            <button
              key={range}
              className={range === days ? "active" : ""}
              onClick={() => onRangeChange(range)}
            >
              {range} d
            </button>
          ))}
        </div>
      </div>
      <div className="chart">
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={chartData}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis
              dataKey="day"
              tickFormatter={(day: string) => day.slice(5)}
              minTickGap={24}
            />
            <YAxis
              yAxisId="energy"
              tickFormatter={(mwh: number) => mwh.toFixed(0)}
            />
            <YAxis yAxisId="wind" orientation="right" width={40} />
            <Tooltip content={<DailyTooltip />} />
            <Legend />
            <Bar yAxisId="energy" dataKey="energy_mwh" name="Tagesenergie">
              {chartData.map((entry, index) => (
                <Cell key={entry.day} fill={barColor(daily[index])} />
              ))}
            </Bar>
            <Line
              yAxisId="wind"
              dataKey="mean_wind_ms"
              name="Mittlere Windgeschwindigkeit (m/s)"
              stroke="#b45309"
              dot={false}
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
    </>
  );
}

function DailyTooltip({
  active,
  payload,
}: {
  active?: boolean;
  payload?: { payload: DailyPoint }[];
}) {
  if (!active || !payload || payload.length === 0) return null;
  const point = payload[0].payload;

  return (
    <div className="tooltip">
      <div className="tooltip-title">
        {new Date(point.day).toLocaleDateString("de-DE")}
      </div>
      <div>
        Energie: <strong>{asMWh(point.energy_kwh)} MWh</strong>
      </div>
      <div>
        Mittlerer Wind: {asMs(point.mean_wind_ms)} m/s
        {point.max_wind_ms != null && ` · max ${asMs(point.max_wind_ms)} m/s`}
      </div>
      <div>
        Verwertbare Stunden: {asHours(point.hours)}/24
      </div>
      <div>
        QC: {point.suspect_hours} verdächtig · {point.missing_hours} ohne Wert
      </div>
    </div>
  );
}
