/** Ingest history — the last 10 runs from /api/ingest/runs (plan phase 4). */
import type { IngestRun } from "../api";
import { asClock, asDuration, asHours, asStatus } from "../format";

export function IngestHistory({ runs }: { runs: IngestRun[] }) {
  if (runs.length === 0) {
    return <p>Noch kein Ingest-Lauf aufgezeichnet.</p>;
  }

  return (
    <table className="history">
      <thead>
        <tr>
          <th>Gestartet</th>
          <th>Status</th>
          <th>Dauer</th>
          <th>Seiten</th>
          <th>Zeilen (neu/geändert)</th>
          <th>QC (o. W./verd./fehler)</th>
          <th>Maximale Lücke</th>
          <th>Details</th>
        </tr>
      </thead>
      <tbody>
        {runs.map((run) => (
          <tr key={run.id}>
            <td>{asClock(run.started_at)}</td>
            <td>
              <span className={`pill pill-${run.status}`}>{asStatus(run.status)}</span>
            </td>
            <td>{asDuration(run.started_at, run.finished_at)}</td>
            <td>{run.pages}</td>
            <td>
              {run.inserted} / {run.updated}
            </td>
            <td>
              {run.qc_missing} / {run.qc_suspect} / {run.qc_malformed}
            </td>
            <td>{asHours(run.max_gap_hours)} h</td>
            <td className="detail">{run.detail ?? "–"}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
