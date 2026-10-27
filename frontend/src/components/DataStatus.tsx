/** Data status — last ingest run (status pill, finished at, duration,
 * inserted/updated, interpolated hours), data age with warning state,
 * coverage %, max gap and a "sync now" button (plan phase 4). */
import { useState } from "react";

import { useQueueIngest } from "../api/generated/windIQAPI";
import type { IngestRun, Metrics } from "../api";
import { asAge, asClock, asHours, asPercent, asDuration, asStatus } from "../format";

/** Data older than this (no fresh measurements/revision) means the worker
 * is likely down — file is the plan's staleness threshold. */
const STALE_AFTER_SECONDS = 3 * 3_600;

export function DataStatus({ metrics, runs }: { metrics: Metrics; runs: IngestRun[] | null }) {
  const { coverage, staleness } = metrics;
  const lastRun = staleness.last_run ?? runs?.[0] ?? null;

  const [queuedAt, setQueuedAt] = useState<number | null>(null);
  const [failedAt, setFailedAt] = useState<number | null>(null);

  // The queued badge and the failure note are derived: both clear once a run
  // started after the request shows up in the polled ingest history.
  const hasRunSince = (since: number) =>
    (runs ?? []).some((run) => new Date(run.started_at).getTime() > since);
  const queued = queuedAt != null && !hasRunSince(queuedAt);
  const queueFailed = failedAt != null && !hasRunSince(failedAt);

  const stale = (staleness.data_age_seconds ?? 0) > STALE_AFTER_SECONDS;

  const queueIngest = useQueueIngest();

  const queueSync = async () => {
    try {
      setQueuedAt(Date.now());
      setFailedAt(null);
      await queueIngest.mutateAsync({ params: { mode: "sync" } });
    } catch {
      setQueuedAt(null);
      setFailedAt(Date.now());
    }
  };

  return (
    <div className="status-grid">
      <div>
        <h3 className="chart-title">Letzter Ingest-Lauf</h3>
        <ul className="status-list">
          {lastRun ? (
            <>
              <li>
                <span className={`pill pill-${lastRun.status}`}>{asStatus(lastRun.status)}</span>
                {queued && <span className="pill pill-queued">in Warteschlange…</span>}
              </li>
              <li>
                Abgeschlossen: {asClock(lastRun.finished_at)} · Dauer{" "}
                {asDuration(lastRun.started_at, lastRun.finished_at)}
              </li>
              <li>
                Seiten {lastRun.pages} · {lastRun.inserted} neu · {lastRun.updated} geändert
                {lastRun.interpolated > 0 && ` · ${lastRun.interpolated} Stunden interpoliert`}
              </li>
            </>
          ) : (
            <li>Noch kein Ingest-Lauf aufgezeichnet.</li>
          )}
        </ul>
        <button className="action" onClick={() => void queueSync()}>
          {queued ? "In Warteschlange…" : "Winddaten abrufen"}
        </button>
        {queueFailed && (
          <p className="error-note">Einreihung fehlgeschlagen — bitte später erneut versuchen.</p>
        )}
      </div>

      <div>
        <h3 className="chart-title">Datenabdeckung</h3>
        <ul className="status-list">
          <li>
            Datenalter:{" "}
            {stale ? (
              <span className="warn">{asAge(staleness.data_age_seconds)} (veraltet)</span>
            ) : (
              asAge(staleness.data_age_seconds)
            )}
          </li>
          <li>
            Abdeckung: {asPercent(coverage.total_hours, coverage.expected_hours)} % (
            {asHours(coverage.total_hours)} von {asHours(coverage.expected_hours)} h)
          </li>
          <li>
            {coverage.interpolated_hours > 0
              ? `${asHours(coverage.interpolated_hours)} Stunden interpoliert`
              : "Werte unverändert aus der Quelle"}
            {coverage.absent_hours > 0 && ` · ${asHours(coverage.absent_hours)} h Randlücke`}
          </li>
          <li>
            Maximale Lücke: {asHours(coverage.max_gap_hours)} h innerhalb der letzten 12 Monate
          </li>
          <li>
            Maximale Lücke: {asHours(coverage.max_gap_hours)} h innerhalb der letzten 12 Monate
          </li>
        </ul>
      </div>
    </div>
  );
}
