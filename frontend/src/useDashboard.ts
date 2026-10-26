/** Per-panel polling hook — all four dashboard GETs share the 60 s cadence
 * (paused while the tab is hidden) plus a manual refresh. Independent
 * loading/error state lets each panel degrade on its own. Background polls
 * are silent: no loading toggle, and unchanged payloads don't update state,
 * so idle cycles render nothing. */
import { useCallback, useEffect, useRef, useState } from "react";

import {
  fetchDaily,
  fetchMetrics,
  fetchRuns,
  fetchTurbine,
  fetchWind,
  type DailyPoint,
  type IngestRun,
  type Metrics,
  type TurbineDetail,
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
  turbine: Panel<TurbineDetail | null>;
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
  const turbine = usePolled(fetchTurbine);

  const refreshAll = useCallback(() => {
    metrics.refresh();
    daily.refresh();
    wind.refresh();
    runs.refresh();
    turbine.refresh();
  }, [metrics, daily, wind, runs, turbine]);

  return {
    metrics,
    daily,
    wind,
    runs,
    turbine,
    refreshAll,
    loading: metrics.loading || daily.loading || wind.loading || runs.loading || turbine.loading,
  };
}

function usePolled<T>(load: () => Promise<T>, deps: readonly unknown[] = []): Panel<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const dataJsonRef = useRef<string | null>(null);
  const requestIdRef = useRef(0);
  const loadRef = useRef(load);

  // keep the dispatching loader fresh without re-creating `run`; declared
  // before the fetch effect below so it lands first on the same commit
  useEffect(() => {
    loadRef.current = load;
  });

  const run = useCallback(() => {
    const requestId = ++requestIdRef.current;
    loadRef
      .current()
      .then((result) => {
        // a newer run (e.g. manual refresh racing the poll) supersedes this one
        if (requestId !== requestIdRef.current) return;
        const json = JSON.stringify(result);
        if (json !== dataJsonRef.current) {
          dataJsonRef.current = json;
          setData(result);
        }
        setError(null);
      })
      .catch((err: unknown) => {
        if (requestId !== requestIdRef.current) return;
        setError(err instanceof Error ? err.message : "Unbekannter Fehler");
      })
      .finally(() => {
        if (requestId !== requestIdRef.current) return;
        setLoading(false);
      });
  }, []);

  const refresh = useCallback(() => {
    setLoading(true);
    run();
  }, [run]);

  // `deps` carry the loader's inputs (e.g. the daily range); a change is
  // user-initiated, so it goes through `refresh` for the loading indicators.
  // Background polls below stay silent. Both disables are deliberate: spread
  // deps can't be statically verified, and the loading flag is set
  // synchronously by design in this data-fetching effect.
  useEffect(() => {
    // eslint-disable-next-line react-hooks/exhaustive-deps, react-hooks/set-state-in-effect
    refresh();
  }, [refresh, ...deps]);

  useEffect(() => {
    const timer = setInterval(() => {
      if (!document.hidden) run();
    }, POLL_MS);
    const onVisible = () => {
      if (!document.hidden) run();
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      clearInterval(timer);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [run]);

  return { data, error, loading, refresh };
}
