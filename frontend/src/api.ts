/** Typed access to the backend dashboard API. Types are generated from the
 * FastAPI OpenAPI spec (`npm run generate:api` → src/api/schema.d.ts). */
import type { components, operations } from "./api/schema";

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

/** The backend serializes every response field (nulls included), but pydantic
 * field defaults mark them optional in the spec — strip the phantom undefined. */
type Payload<T> = { [K in keyof T]-?: PayloadField<T[K]> };
type PayloadField<V> = PayloadValue<Exclude<V, undefined>>;
type PayloadValue<W> = W extends (infer U)[] ? Payload<U>[] : W extends object ? Payload<W> : W;

export type Metrics = Payload<components["schemas"]["MetricsOut"]>;
export type DailyPoint = Payload<components["schemas"]["DailyPointOut"]>;
export type WindResponse = Payload<components["schemas"]["WindOut"]>;
export type IngestRun = Payload<components["schemas"]["IngestRunOut"]>;
export type TurbineDetail = Payload<components["schemas"]["TurbineDetailOut"]>;
export type PowerCurvePoint = Payload<components["schemas"]["PowerCurvePointOut"]>;
export type RoseSector = Payload<components["schemas"]["RoseSectorOut"]>;

type IngestQuery = NonNullable<
  operations["queue_ingest_api_ingest_run_post"]["parameters"]["query"]
>;
export type IngestMode = NonNullable<IngestQuery["mode"]>;

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

export function fetchTurbine(): Promise<TurbineDetail | null> {
  return getJson<TurbineDetail | null>("/api/turbine");
}

export async function postIngestRun(mode: IngestMode): Promise<boolean> {
  const body = await post(`/api/ingest/run?mode=${mode}`);
  return body["queued"] === true;
}
