/** Typed access to the backend dashboard API (see backend/app/api.py). */

async function getJson<T>(url: string): Promise<T> {
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`GET ${url} failed (HTTP ${response.status})`);
  }
  return (await response.json()) as T;
}

async function post(url: string): Promise<Record<string, unknown>> {
  const response = await fetch(url, { method: "POST" });
  if (!response.ok) {
    throw new Error(`POST ${url} failed (HTTP ${response.status})`);
  }
  return (await response.json()) as Record<string, unknown>;
}

export interface AepChain {
  gross_kwh: number;
  net_kwh: number | null;
  p50_kwh: number | null;
  p90_kwh: number | null;
  window_start: string | null;
  window_end: string | null;
  usable_hours: number;
}

export interface Coverage {
  from_ts: string | null;
  to_ts: string | null;
  total_hours: number;
  usable_hours: number;
  suspect_hours: number;
  missing_hours: number;
  malformed_hours: number;
  expected_hours: number;
  absent_hours: number;
  max_gap_hours: number | null;
}

export interface SiteInfo {
  name: string;
  shear_exponent: number;
  availability_loss: number;
  electrical_loss: number;
  wake_loss: number;
  uncertainty: number;
}

export interface TurbineInfo {
  name: string;
  rated_power_kw: number;
  hub_height_m: number;
  rotor_diameter_m: number;
}

export interface MastInfo {
  name: string;
  measurement_height_m: number;
}

export interface IngestRun {
  id: number;
  started_at: string;
  finished_at: string | null;
  status: string;
  pages: number;
  inserted: number;
  updated: number;
  frame_from: string | null;
  frame_to: string | null;
  qc_missing: number;
  qc_suspect: number;
  qc_malformed: number;
  max_gap_hours: number | null;
  detail: string | null;
}

export interface Metrics {
  aep: AepChain;
  coverage: Coverage;
  site: SiteInfo | null;
  turbine: TurbineInfo | null;
  mast: MastInfo | null;
  staleness: {
    last_run: IngestRun | null;
    data_age_seconds: number | null;
  };
}

export interface DailyPoint {
  day: string;
  /** NULL → day without any ok hours (gap); the SPA draws it as absent. */
  energy_kwh: number | null;
  hours: number | null;
  mean_wind_ms: number | null;
  max_wind_ms: number | null;
  suspect_hours: number;
  /** sentinel + malformed rows of that day ("no usable data" hours) */
  missing_hours: number;
}

export interface WindPoint {
  timestamp: string;
  wind_speed_ms: number;
  wind_dir_deg: number;
}

export interface RoseSector {
  direction: string;
  degrees: number;
  frequency: number;
  mean_speed_ms: number | null;
}

export interface WindResponse {
  hours: number;
  series: WindPoint[];
  rose: RoseSector[];
}

export function fetchMetrics(): Promise<Metrics> {
  return getJson<Metrics>("/api/metrics");
}

export function fetchDaily(days: number): Promise<DailyPoint[]> {
  return getJson<DailyPoint[]>(`/api/daily?days=${days}`);
}

export function fetchWind(hours: number = 48): Promise<WindResponse> {
  return getJson<WindResponse>(`/api/wind?hours=${hours}`);
}

export function fetchRuns(limit: number = 10): Promise<IngestRun[]> {
  return getJson<IngestRun[]>(`/api/ingest/runs?limit=${limit}`);
}

export type IngestMode = "sync" | "backfill";

export async function postIngestRun(mode: IngestMode): Promise<boolean> {
  const body = await post(`/api/ingest/run?mode=${mode}`);
  return body["queued"] === true;
}
