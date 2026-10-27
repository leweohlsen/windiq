import { useState, type ReactNode } from "react";
import { keepPreviousData, useIsFetching, useQueryClient } from "@tanstack/react-query";
import type { UseQueryResult } from "@tanstack/react-query";

import logoUrl from "./assets/windiq-logo.png";

import { Header } from "./components/Header";
import { DailyChart } from "./components/DailyChart";
import { WindPanel } from "./components/WindPanel";
import { DataStatus } from "./components/DataStatus";
import { IngestHistory } from "./components/IngestHistory";
import { Methodology } from "./components/Methodology";
import { ReferenceTurbine } from "./components/ReferenceTurbine";
import {
  useDaily,
  useIngestRuns,
  useMetrics,
  useTurbine,
  useWind,
} from "./api/generated/windIQAPI";

/** All dashboard GETs share the 60 s cadence (paused while the tab is
 * hidden); unchanged payloads don't re-render (structural sharing). */
const POLL_MS = 60_000;
const WIND_HOURS = 48;
const RUNS_LIMIT = 10;
const DAILY_RANGES = [30, 90, 365];

function App() {
  const [days, setDays] = useState(90);
  const queryClient = useQueryClient();

  const metrics = useMetrics({ query: { refetchInterval: POLL_MS } });
  // keepPreviousData: a range change re-fetches under a new key but keeps the
  // old chart visible (refreshing dim) instead of flashing the skeleton
  const daily = useDaily({ days }, { query: { refetchInterval: POLL_MS, placeholderData: keepPreviousData } });
  const wind = useWind({ hours: WIND_HOURS }, { query: { refetchInterval: POLL_MS } });
  const runs = useIngestRuns({ limit: RUNS_LIMIT }, { query: { refetchInterval: POLL_MS } });
  const turbine = useTurbine({ query: { refetchInterval: POLL_MS } });

  const panels = [metrics, daily, wind, runs, turbine];
  // True while any fetch is in flight (for the global refresh button).
  const loading = useIsFetching() > 0;

  // Skeleton gate: the dashboard appears in one piece once every panel holds
  // its first data (or error) — no sections popping in one by one. A panel
  // that finished without data (e.g. no turbine yet) lifts the gate too;
  // PanelState then shows its empty state.
  const booting = panels.some((panel) => panel.isPending);

  const refreshAll = () => void queryClient.refetchQueries();

  return (
    <main>
      {/* user-initiated fetches: indeterminate sweep, fixed so nothing shifts */}
      <div className={loading ? "progress active" : "progress"} aria-hidden="true" />

      <header className="masthead">
        <img src={logoUrl} alt="WindIQ" />
        <button onClick={refreshAll} disabled={loading}>
          {loading ? "Aktualisiere…" : "Aktualisieren"}
        </button>
      </header>

      {booting ? (
        <DashboardSkeleton days={days} onRangeChange={setDays} />
      ) : (
        <div className="dashboard">
          <section>
            <PanelState query={metrics}>{(metrics) => <Header metrics={metrics} />}</PanelState>
          </section>

          <section className="panel">
            <DailyHead days={days} onRangeChange={setDays} />
            <PanelState query={daily}>{(daily) => <DailyChart daily={daily} />}</PanelState>
          </section>

          <section className="panel">
            <PanelState query={wind}>{(wind) => <WindPanel wind={wind} />}</PanelState>
          </section>

          <section className="panel">
            <h2>Referenzanlage</h2>
            <PanelState query={turbine}>
              {(turbine) => turbine && <ReferenceTurbine turbine={turbine} />}
            </PanelState>
          </section>

          <section className="panel">
            <h2>Datenstatus</h2>
            <PanelState query={metrics}>
              {(metrics) => (
                <PanelState query={runs}>
                  {(runs) => <DataStatus metrics={metrics} runs={runs} />}
                </PanelState>
              )}
            </PanelState>
            <h3 className="chart-title ingest-title">Ingest-Verlauf</h3>
            <PanelState query={runs}>{(runs) => <IngestHistory runs={runs} />}</PanelState>
          </section>

          <section className="panel">
            <h2>Berechnungsmethode</h2>
            <PanelState query={metrics}>
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
function PanelState<T>({
  query,
  children,
}: {
  query: UseQueryResult<T, unknown>;
  children: (data: T) => ReactNode;
}) {
  const error = query.error instanceof Error ? query.error.message : query.error ? "Unbekannter Fehler" : null;
  if (query.data == null) {
    if (error) {
      return (
        <p className="panel-empty">
          Laden fehlgeschlagen — {error}{" "}
          <button onClick={() => void query.refetch()} disabled={query.isFetching}>
            {query.isFetching ? "Lädt…" : "Erneut versuchen"}
          </button>
        </p>
      );
    }
    return <p className="panel-empty">{query.isPending ? "Laden…" : "Keine Daten."}</p>;
  }
  const classes = ["data"];
  if (error) classes.push("stale-refresh");
  if (query.isFetching) classes.push("refreshing");
  return (
    <div className={classes.join(" ")}>
      {error && (
        <p className="error-note">
          Letzte Aktualisierung fehlgeschlagen — es werden die letzten Daten angezeigt.
        </p>
      )}
      {children(query.data)}
    </div>
  );
}

export default App;
