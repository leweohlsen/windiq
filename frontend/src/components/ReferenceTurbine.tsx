/** ReferenceTurbine — spec cards plus the power curve (Wirkungskurve) from
 * /api/turbine; swept area and specific power are derived from the specs. */
import { memo } from "react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import type { PowerCurvePoint, TurbineDetail } from "../api";
import { useAnimateOnce } from "../useAnimateOnce";
import { asNum } from "../format";

const LINE = "#3b82f6";
const MUTED = "#6b7280";

export const ReferenceTurbine = memo(function ReferenceTurbine({
  turbine,
}: {
  turbine: TurbineDetail;
}) {
  const animate = useAnimateOnce();

  const sweptAreaM2 = (Math.PI / 4) * turbine.rotor_diameter_m ** 2;
  const specificPowerWm2 = (turbine.rated_power_kw * 1000) / sweptAreaM2;

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
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={turbine.power_curve} margin={{ top: 20, right: 12 }}>
                <defs>
                  <linearGradient id="power-curve-fill" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor={LINE} stopOpacity={0.35} />
                    <stop offset="100%" stopColor={LINE} stopOpacity={0.02} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" vertical={false} />
                {/* numeric axis: spacing proportional to wind speed, not per point */}
                <XAxis
                  dataKey="wind_speed_ms"
                  type="number"
                  domain={[0, "dataMax"]}
                  ticks={xTicks(turbine)}
                  tickFormatter={(v: number) => v.toFixed(0)}
                />
                <YAxis
                  width={48}
                  domain={[0, Math.ceil(turbine.rated_power_kw / 1000) * 1000]}
                  tickFormatter={(kw: number) => kw.toFixed(0)}
                />
                <Tooltip content={<CurveTooltip />} />
                <ReferenceLine
                  y={turbine.rated_power_kw}
                  stroke={MUTED}
                  strokeDasharray="4 4"
                  label={{
                    value: `Nennleistung ${asNum(turbine.rated_power_kw, 0)} kW`,
                    position: "insideTopRight",
                    fontSize: 11,
                    fill: MUTED,
                  }}
                />
                <ReferenceLine
                  x={turbine.cut_in_wind_speed_ms}
                  stroke={MUTED}
                  strokeDasharray="4 4"
                  label={{
                    value: `Cut-in ${asNum(turbine.cut_in_wind_speed_ms, 1)} m/s`,
                    position: "insideTopLeft",
                    fontSize: 11,
                    fill: MUTED,
                  }}
                />
                <ReferenceLine
                  x={turbine.cut_out_wind_speed_ms}
                  stroke={MUTED}
                  strokeDasharray="4 4"
                  label={{
                    value: `Cut-out ${asNum(turbine.cut_out_wind_speed_ms, 1)} m/s`,
                    position: "insideBottomRight",
                    fontSize: 11,
                    fill: MUTED,
                  }}
                />
                <Area
                  dataKey="power_kw"
                  name="Leistung (kW)"
                  type="monotone"
                  stroke={LINE}
                  strokeWidth={2}
                  fill="url(#power-curve-fill)"
                  activeDot={{ r: 4 }}
                  isAnimationActive={animate}
                />
              </AreaChart>
            </ResponsiveContainer>
          </div>
          <p className="chart-note">Windgeschwindigkeit (m/s) → Leistung (kW), 1-m/s-Schritte</p>
        </div>
      </div>
    </>
  );
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

function CurveTooltip({
  active,
  payload,
}: {
  active?: boolean;
  payload?: { payload: PowerCurvePoint }[];
}) {
  if (!active) return null;
  const point = payload?.[0]?.payload;
  if (!point) return null;
  return (
    <div className="tooltip">
      <div className="tooltip-title">{asNum(point.wind_speed_ms, 1)} m/s Wind</div>
      <div>
        Leistung: <strong>{asNum(point.power_kw, 0)} kW</strong>
      </div>
    </div>
  );
}
