import { vi } from "vitest";

const metrics = {
  aep: { p50_kwh: 1 },
  coverage: {},
  site: null,
  turbine: null,
  mast: null,
  staleness: { last_run: null, data_age_seconds: 60 },
};

/** Shared in-memory /api for tests. Values are JSON bodies, Error instances
 * (the fetch rejects) or Promises (deferred responses). Mutate between polls
 * to simulate changed data. */
export function stubDashboardFetch() {
  const responses: Record<string, unknown> = {
    "/api/metrics": metrics,
    "/api/daily?days=90": [{ day: "2026-10-25", energy_kwh: 1 }],
    "/api/wind?hours=48": { hours: 48, series: [], rose: [] },
    "/api/ingest/runs?limit=10": [],
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

export { metrics };
