/** Header — two stat cards (P50/P90, GWh) plus gross/net AEP, measurement
 * range, usable vs. expected hours and the site metadata line (plan phase 4). */
import type { Metrics } from "../api";
import { asDateRange, asGWh, asHours, asPercent } from "../format";

export function Header({ metrics }: { metrics: Metrics }) {
  const { aep, coverage, site, turbine, mast } = metrics;

  const subtitle = [
    site?.name,
    turbine ? `${turbine.name} (Nabe ${turbine.hub_height_m} m)` : null,
    mast ? `${mast.name} (Mast ${mast.measurement_height_m} m)` : null,
  ]
    .filter(Boolean)
    .join(" · ");

  return (
    <>
      <p className="subtitle">{subtitle || "Noch keine Referenzdaten"}</p>

      <div className="cards">
        <div className="card stat">
          <span className="label">P50 · letzte 12 Monate</span>
          <span className="value">{asGWh(aep.p50_kwh)} GWh</span>
        </div>
        <div className="card stat">
          <span className="label">P90 · letzte 12 Monate</span>
          <span className="value">{asGWh(aep.p90_kwh)} GWh</span>
        </div>
      </div>

      <div className="cards">
        <div className="card">
          <span className="label">AEP brutto</span>
          <span className="value small">{asGWh(aep.gross_kwh)} GWh</span>
        </div>
        <div className="card">
          <span className="label">AEP netto</span>
          <span className="value small">{asGWh(aep.net_kwh)} GWh</span>
        </div>
        <div className="card">
          <span className="label">Messzeitraum</span>
          <span className="value small">
            {asDateRange(coverage.from_ts, coverage.to_ts)}
          </span>
        </div>
        <div className="card">
          <span className="label">Verwertbare Stunden</span>
          <span className="value small">
            {asHours(coverage.usable_hours)} / {asHours(coverage.expected_hours)} h (
            {asPercent(coverage.usable_hours, coverage.expected_hours)} %)
          </span>
        </div>
      </div>
    </>
  );
}
