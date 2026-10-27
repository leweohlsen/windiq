import { vi } from "vitest";

const metrics = {
  aep: { p50_kwh: 1 },
  coverage: {},
  site: null,
  turbine: null,
  mast: null,
  staleness: { last_run: null, data_age_seconds: 60 },
};

const turbine = {
  name: "Test turbine",
  rated_power_kw: 3600,
  hub_height_m: 140,
  rotor_diameter_m: 136,
  cut_in_wind_speed_ms: 3,
  cut_out_wind_speed_ms: 25,
  power_curve: [
    { wind_speed_ms: 0, power_kw: 0 },
    { wind_speed_ms: 10, power_kw: 1800 },
    { wind_speed_ms: 20, power_kw: 3600 },
  ],
};

/** Shared in-memory /api for tests. Values are JSON bodies, Error instances
 * (the fetch rejects) or Promises (deferred responses). Mutate between polls
 * to simulate changed data. */
export function stubDashboardFetch() {
  const responses: Record<string, unknown> = {
    "/api/metrics": metrics,
    "/api/daily?days=90": [{ day: "2026-10-25", energy_kwh: 1 }],
    "/api/wind?days=2&resolution=hour": {
      days: 2,
      resolution: "hour",
      series: makeWindSeries(48),
      rose: [],
    },
    "/api/wind?days=7&resolution=hour": {
      days: 7,
      resolution: "hour",
      series: makeWindSeries(168),
      rose: [],
    },
    "/api/wind?days=7&resolution=day": {
      days: 7,
      resolution: "day",
      series: makeWindSeries(7),
      rose: [],
    },
    "/api/ingest/runs?limit=10": [],
    "/api/turbine": turbine,
  };

  const fetchMock = vi.fn(async (input: string | URL | Request) => {
    const url =
      typeof input === "string" ? input : input instanceof Request ? input.url : input.toString();
    const key = Object.keys(responses).find((k) => url.startsWith(k));
    if (key == null) throw new Error(`unexpected fetch: ${url}`);
    const body = responses[key];
    if (body instanceof Error) throw body;
    return { ok: true, json: async () => body } as Response;
  });
  vi.stubGlobal("fetch", fetchMock);

  return { fetchMock, responses };
}

/** Tests run with the tab visible so background polls fire. */
export function showTab() {
  Object.defineProperty(document, "hidden", { configurable: true, value: false });
}

/** Generate a synthetic hourly wind series for tests. Timestamps are UTC
 * hours ending at the current hour; mean wind oscillates 3–12 m/s. */
function makeWindSeries(count: number) {
  const now = new Date();
  now.setUTCMinutes(0, 0, 0);
  return Array.from({ length: count }, (_, i) => {
    const ts = new Date(now.getTime() - (count - 1 - i) * 3600_000).toISOString();
    const mean = 7.5 + Math.sin(i / 6) * 4;
    return {
      timestamp: ts,
      mean_wind_ms: mean,
      min_wind_ms: mean - 1,
      max_wind_ms: mean + 1,
      ok_hours: 1,
      suspect_hours: 0,
      missing_hours: 0,
      malformed_hours: 0,
    };
  });
}

export { metrics, turbine };
