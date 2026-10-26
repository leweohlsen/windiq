/** Data status — last ingest run (status pill, finished at, duration,
 * inserted/updated, QC counts), data age with warning state, coverage %,
 * QC totals, max gap and a "sync now" button (plan phase 4). */
import { useState } from "react";

import { postIngestRun } from "../api";
import type { IngestRun, Metrics } from "../api";
import { asAge, asClock, asHours, asPercent, asDuration, asStatus } from "../format";
import { STALE_AFTER_SECONDS } from "../useDashboard";

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

  const queueSync = async () => {
    try {
      setQueuedAt(Date.now());
      setFailedAt(null);
      await postIngestRun("sync");
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
              </li>
              {(lastRun.qc_missing > 0 || lastRun.qc_suspect > 0 || lastRun.qc_malformed > 0) && (
                <li>
                  QC des Laufs: {lastRun.qc_missing} ohne Wert · {lastRun.qc_suspect} verdächtig ·{" "}
                  {lastRun.qc_malformed} fehlerhaft
                </li>
              )}
            </>
          ) : (
            <li>Noch kein Ingest-Lauf aufgezeichnet.</li>
          )}
        </ul>
        <button className="action" onClick={() => void queueSync()}>
          {queued ? "In Warteschlange…" : "Jetzt synchronisieren"}
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
            Abdeckung: {asPercent(coverage.usable_hours, coverage.expected_hours)} % (
            {asHours(coverage.usable_hours)} von {asHours(coverage.expected_hours)} h)
          </li>
          <li>
            QC-Statistik: {asHours(coverage.absent_hours)} nicht geliefert ·{" "}
            {asHours(coverage.missing_hours)} ohne Wert · {asHours(coverage.suspect_hours)}{" "}
            verdächtig · {asHours(coverage.malformed_hours)} fehlerhaft
          </li>
          <li>
            Maximale Lücke: {asHours(coverage.max_gap_hours)} h innerhalb der letzten 12 Monate
          </li>
        </ul>
      </div>
    </div>
  );
}
