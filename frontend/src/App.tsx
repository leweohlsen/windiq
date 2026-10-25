import { useState, type ReactNode } from "react";

import logoUrl from "./assets/windiq-logo.png";

import { Header } from "./components/Header";
import { DailyChart } from "./components/DailyChart";
import { WindPanel } from "./components/WindPanel";
import { DataStatus } from "./components/DataStatus";
import { IngestHistory } from "./components/IngestHistory";
import { Methodology } from "./components/Methodology";
import { useDashboard } from "./useDashboard";

function App() {
  const [days, setDays] = useState(90);
  const dashboard = useDashboard(days);

  return (
    <main>
      <header className="masthead">
        <img src={logoUrl} alt="WindIQ" />
        <button onClick={dashboard.refreshAll}>
          {dashboard.loading ? "Aktualisiere…" : "Aktualisieren"}
        </button>
      </header>

      <section>
        <PanelState panel={dashboard.metrics}>
          {(metrics) => <Header metrics={metrics} />}
        </PanelState>
      </section>

      <section className="panel">
        <PanelState panel={dashboard.daily}>
          {(daily) => (
            <DailyChart daily={daily} days={days} onRangeChange={setDays} />
          )}
        </PanelState>
      </section>

      <section className="panel">
        <h2>Wind</h2>
        <PanelState panel={dashboard.wind}>{(wind) => <WindPanel wind={wind} />}</PanelState>
      </section>

      <section className="panel">
        <h2>Datenstatus</h2>
        <PanelState panel={dashboard.runs}>
          {(runs) => (
            <PanelState panel={dashboard.metrics}>
              {(metrics) => <DataStatus metrics={metrics} runs={runs} />}
            </PanelState>
          )}
        </PanelState>
      </section>

      <section className="panel">
        <h2>Ingest-Verlauf</h2>
        <PanelState panel={dashboard.runs}>{(runs) => <IngestHistory runs={runs} />}</PanelState>
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
    </main>
  );
}

/** Per-panel loading/error states: stale data stays visible after a failed
 * refresh, an empty panel shows failed/Retry (plan phase 4). */
function PanelState<T>({
  panel,
  children,
}: {
  panel: { data: T | null; error: string | null; loading: boolean; refresh: () => void };
  children: (data: T) => ReactNode;
}) {
  if (panel.data == null) {
    if (panel.error) {
      return (
        <p className="panel-empty">
          Laden fehlgeschlagen — {panel.error}{" "}
          <button onClick={panel.refresh}>Erneut versuchen</button>
        </p>
      );
    }
    return <p className="panel-empty">{panel.loading ? "Laden…" : "Keine Daten."}</p>;
  }
  return (
    <div className={panel.error ? "data stale-refresh" : "data"}>
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
