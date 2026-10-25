/** Per-panel polling hook — all four dashboard GETs share the 60 s cadence
 * (paused while the tab is hidden) plus a manual refresh. Independent
 * loading/error state lets each panel degrade on its own. */
import { useCallback, useEffect, useRef, useState } from "react";

import {
  fetchDaily,
  fetchMetrics,
  fetchRuns,
  fetchWind,
  type DailyPoint,
  type IngestRun,
  type Metrics,
  type WindResponse,
} from "./api";

const POLL_MS = 60_000;

export interface Panel<T> {
  data: T | null;
  error: string | null;
  loading: boolean;
  refresh: () => void;
}

export interface DashboardState {
  metrics: Panel<Metrics>;
  daily: Panel<DailyPoint[]>;
  wind: Panel<WindResponse>;
  runs: Panel<IngestRun[]>;
  refreshAll: () => void;
  /** True while any panel's fetch is in flight (for the global refresh button). */
  loading: boolean;
}

export const WIND_HOURS = 48;
export const RUNS_LIMIT = 10;
export const DAILY_RANGES = [30, 90, 365];

/** Data older than this (no fresh measurements/revision) means the worker
 * is likely down — file is the plan's staleness threshold. */
export const STALE_AFTER_SECONDS = 3 * 3_600;

/** `days` is the daily-chart range: passed as a dep, so a range change re-fetches. */
export function useDashboard(days: number): DashboardState {
  const metrics = usePolled(fetchMetrics);
  const daily = usePolled(() => fetchDaily(days), [days]);
  const wind = usePolled(() => fetchWind(WIND_HOURS));
  const runs = usePolled(() => fetchRuns(RUNS_LIMIT));

  const refreshAll = useCallback(() => {
    metrics.refresh();
    daily.refresh();
    wind.refresh();
    runs.refresh();
  }, [metrics, daily, wind, runs]);

  return {
    metrics,
    daily,
    wind,
    runs,
    refreshAll,
    loading: metrics.loading || daily.loading || wind.loading || runs.loading,
  };
}

function usePolled<T>(load: () => Promise<T>, deps: readonly unknown[] = []): Panel<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const loadRef = useRef(load);
  loadRef.current = load;

  const refresh = useCallback(() => {
    setLoading(true);
    loadRef
      .current()
      .then((result) => {
        setData(result);
        setError(null);
      })
      .catch((err: unknown) => {
        setError(err instanceof Error ? err.message : "Unbekannter Fehler");
      })
      .finally(() => setLoading(false));
  }, []);

  // `deps` carry the loader's inputs (e.g. the daily range); the dispatching
  // loader itself is always fresh via `loadRef`
  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refresh, ...deps]);

  useEffect(() => {
    const timer = setInterval(() => {
      if (!document.hidden) refresh();
    }, POLL_MS);
    const onVisible = () => {
      if (!document.hidden) refresh();
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      clearInterval(timer);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [refresh]);

  return { data, error, loading, refresh };
}
