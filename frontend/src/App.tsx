import { useState, type ReactNode } from "react";

import logoUrl from "./assets/windiq-logo.png";

import { Header } from "./components/Header";
import { DailyChart } from "./components/DailyChart";
import { WindPanel } from "./components/WindPanel";
import { DataStatus } from "./components/DataStatus";
import { IngestHistory } from "./components/IngestHistory";
import { Methodology } from "./components/Methodology";
import { ReferenceTurbine } from "./components/ReferenceTurbine";
import { DAILY_RANGES, useDashboard, type Panel } from "./useDashboard";

function App() {
  const [days, setDays] = useState(90);
  const dashboard = useDashboard(days);

  // Skeleton gate: the dashboard appears in one piece once every panel holds
  // its first data (or error) — no sections popping in one by one. A panel
  // that finished without data (e.g. no turbine yet) lifts the gate too;
  // PanelState then shows its empty state.
  const booting = [
    dashboard.metrics,
    dashboard.daily,
    dashboard.wind,
    dashboard.runs,
    dashboard.turbine,
  ].some((panel) => panel.data == null && panel.error == null && panel.loading);

  return (
    <main>
      {/* user-initiated fetches: indeterminate sweep, fixed so nothing shifts */}
      <div className={dashboard.loading ? "progress active" : "progress"} aria-hidden="true" />

      <header className="masthead">
        <img src={logoUrl} alt="WindIQ" />
        <button onClick={dashboard.refreshAll} disabled={dashboard.loading}>
          {dashboard.loading ? "Aktualisiere…" : "Aktualisieren"}
        </button>
      </header>

      {booting ? (
        <DashboardSkeleton days={days} onRangeChange={setDays} />
      ) : (
        <div className="dashboard">
          <section>
            <PanelState panel={dashboard.metrics}>
              {(metrics) => <Header metrics={metrics} />}
            </PanelState>
          </section>

          <section className="panel">
            <DailyHead days={days} onRangeChange={setDays} />
            <PanelState panel={dashboard.daily}>
              {(daily) => <DailyChart daily={daily} />}
            </PanelState>
          </section>

          <section className="panel">
            <PanelState panel={dashboard.wind}>{(wind) => <WindPanel wind={wind} />}</PanelState>
          </section>

          <section className="panel">
            <h2>Referenzanlage</h2>
            <PanelState panel={dashboard.turbine}>
              {(turbine) => turbine && <ReferenceTurbine turbine={turbine} />}
            </PanelState>
          </section>

          <section className="panel">
            <h2>Datenstatus</h2>
            <PanelState panel={dashboard.metrics}>
              {(metrics) => (
                <PanelState panel={dashboard.runs}>
                  {(runs) => <DataStatus metrics={metrics} runs={runs} />}
                </PanelState>
              )}
            </PanelState>
            <h3 className="chart-title ingest-title">Ingest-Verlauf</h3>
            <PanelState panel={dashboard.runs}>
              {(runs) => <IngestHistory runs={runs} />}
            </PanelState>
          </section>

          <section className="panel">
            <h2>Berechnungsmethode</h2>
            <PanelState panel={dashboard.metrics}>
              {(metrics) => <Methodology metrics={metrics} />}
            </PanelState>
          </section>

          <footer>
            API unter <code>/api</code> · Doku unter{" "}
            <a href="/api/docs" target="_blank" rel="noreferrer">
              /api/docs
            </a>
            · Werte aktualisieren sich alle 60 s
          </footer>
        </div>
      )}
    </main>
  );
}

function DailyHead({
  days,
  onRangeChange,
}: {
  days: number;
  onRangeChange: (days: number) => void;
}) {
  return (
    <div className="panel-head">
      <h2>Tagesenergie ({days} Tage)</h2>
      <div className="range-switch">
        {DAILY_RANGES.map((range) => (
          <button
            key={range}
            className={range === days ? "active" : ""}
            aria-pressed={range === days}
            onClick={() => onRangeChange(range)}
          >
            {range} d
          </button>
        ))}
      </div>
    </div>
  );
}

/** First-load skeleton — reuses the dashboard's real layout containers so the
 * single fade-in to the loaded page happens at identical heights. Inert:
 * purely visual, nothing to interact with for a split second. */
function DashboardSkeleton({
  days,
  onRangeChange,
}: {
  days: number;
  onRangeChange: (days: number) => void;
}) {
  return (
    <div inert>
      <section>
        <p className="subtitle">
          <span className="skel skel-line" />
        </p>
        <div className="cards">
          {Array.from({ length: 5 }, (_, i) => (
            <div key={i} className="card skel-card" />
          ))}
        </div>
      </section>

      <section className="panel">
        <DailyHead days={days} onRangeChange={onRangeChange} />
        <div className="chart skel" />
      </section>

      <section className="panel">
        <div className="charts-row">
          <div>
            <h3 className="chart-title">Windrose</h3>
            <div className="chart chart-rose skel" />
            <p className="chart-note">0° N · 90° E · 180° S · 270° W (im Uhrzeigersinn)</p>
          </div>
          <div>
            <h3 className="chart-title">Windgeschwindigkeit</h3>
            <div className="chart skel" />
          </div>
        </div>
      </section>

      <section className="panel">
        <h2>Referenzanlage</h2>
        <div className="charts-row">
          <div className="cards">
            {Array.from({ length: 6 }, (_, i) => (
              <div key={i} className="card skel-card" />
            ))}
          </div>
          <div>
            <h3 className="chart-title">Leistungskurve (Wirkungskurve)</h3>
            <div className="chart skel" />
          </div>
        </div>
      </section>

      <section className="panel">
        <h2>Datenstatus</h2>
        <div className="status-grid">
          <div className="skel skel-block" />
          <div className="skel skel-block" />
        </div>
        <h3 className="chart-title ingest-title">Ingest-Verlauf</h3>
        <div className="skel skel-table" />
      </section>

      <section className="panel">
        <h2>Berechnungsmethode</h2>
        <div className="skel skel-block skel-method" />
      </section>
    </div>
  );
}

/** Per-panel loading/error states: stale data stays visible after a failed
 * refresh, an empty panel shows failed/Retry (plan phase 4). A panel that is
 * refreshing with data present dims slightly instead of changing layout. */
function PanelState<T>({ panel, children }: { panel: Panel<T>; children: (data: T) => ReactNode }) {
  if (panel.data == null) {
    if (panel.error) {
      return (
        <p className="panel-empty">
          Laden fehlgeschlagen — {panel.error}{" "}
          <button onClick={panel.refresh} disabled={panel.loading}>
            {panel.loading ? "Lädt…" : "Erneut versuchen"}
          </button>
        </p>
      );
    }
    return <p className="panel-empty">{panel.loading ? "Laden…" : "Keine Daten."}</p>;
  }
  const classes = ["data"];
  if (panel.error) classes.push("stale-refresh");
  if (panel.loading) classes.push("refreshing");
  return (
    <div className={classes.join(" ")}>
      {panel.error && (
        <p className="error-note">
          Letzte Aktualisierung fehlgeschlagen — es werden die letzten Daten angezeigt.
        </p>
      )}
      {children(panel.data)}
    </div>
  );
}

export default App;
