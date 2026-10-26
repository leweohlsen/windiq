/** Polling hook behavior: initial load, silent background polls with
 * skip-unchanged, stale-on-error, manual refresh loading state, range-change
 * refetch. */
import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useDashboard } from "./useDashboard";
import { metrics, showTab, stubDashboardFetch } from "./test/helpers";

let fetchMock: ReturnType<typeof stubDashboardFetch>["fetchMock"];
let responses: ReturnType<typeof stubDashboardFetch>["responses"];

beforeEach(() => {
  vi.useFakeTimers();
  showTab();
  ({ fetchMock, responses } = stubDashboardFetch());
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe("useDashboard", () => {
  it("loads all four panels on mount", async () => {
    const { result } = renderHook(() => useDashboard(90));

    expect(result.current.loading).toBe(true);
    await act(async () => {});

    expect(fetchMock).toHaveBeenCalledWith("/api/metrics");
    expect(fetchMock).toHaveBeenCalledWith("/api/daily?days=90");
    expect(fetchMock).toHaveBeenCalledWith("/api/wind?hours=48");
    expect(fetchMock).toHaveBeenCalledWith("/api/ingest/runs?limit=10");
    expect(result.current.metrics.data).toBe(metrics);
    expect(result.current.loading).toBe(false);
  });

  it("keeps data references stable when a poll returns unchanged payloads", async () => {
    const { result } = renderHook(() => useDashboard(90));
    await act(async () => {});
    const before = result.current.metrics.data;

    await act(async () => {
      await vi.advanceTimersByTimeAsync(60_000);
    });

    expect(result.current.metrics.data).toBe(before);
  });

  it("applies changed payloads on background polls without the loading state", async () => {
    const { result } = renderHook(() => useDashboard(90));
    await act(async () => {});
    responses["/api/metrics"] = { ...metrics, staleness: { last_run: null, data_age_seconds: 61 } };

    await act(async () => {
      await vi.advanceTimersByTimeAsync(60_000);
    });

    expect(result.current.metrics.data).not.toBe(metrics);
    expect(result.current.metrics.data?.staleness.data_age_seconds).toBe(61);
    expect(result.current.loading).toBe(false);
  });

  it("keeps stale data visible and sets the error when a poll fails", async () => {
    const { result } = renderHook(() => useDashboard(90));
    await act(async () => {});
    const stale = result.current.metrics.data;
    responses["/api/metrics"] = new Error("boom");

    await act(async () => {
      await vi.advanceTimersByTimeAsync(60_000);
    });

    expect(result.current.metrics.error).toBe("boom");
    expect(result.current.metrics.data).toBe(stale);
  });

  it("shows the loading state only while a manual refresh is in flight", async () => {
    const { result } = renderHook(() => useDashboard(90));
    await act(async () => {});

    let release!: (value: unknown) => void;
    responses["/api/metrics"] = new Promise((resolve) => {
      release = resolve;
    });

    act(() => {
      result.current.refreshAll();
    });
    expect(result.current.loading).toBe(true);

    await act(async () => {
      release(metrics);
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(result.current.loading).toBe(false);
  });

  it("refetches the daily panel when the range changes", async () => {
    const { result, rerender } = renderHook(({ days }: { days: number }) => useDashboard(days), {
      initialProps: { days: 90 },
    });
    await act(async () => {});

    responses["/api/daily?days=30"] = [{ day: "2026-10-25", energy_kwh: 2 }];
    rerender({ days: 30 });
    await act(async () => {});

    expect(fetchMock).toHaveBeenCalledWith("/api/daily?days=30");
    expect(result.current.daily.data).toEqual([{ day: "2026-10-25", energy_kwh: 2 }]);
  });

  it("treats a range change as user-initiated: loading until data arrives", async () => {
    const { result, rerender } = renderHook(({ days }: { days: number }) => useDashboard(days), {
      initialProps: { days: 90 },
    });
    await act(async () => {});

    let release!: (value: unknown) => void;
    responses["/api/daily?days=30"] = new Promise((resolve) => {
      release = resolve;
    });

    rerender({ days: 30 });
    await act(async () => {});
    expect(result.current.loading).toBe(true);

    await act(async () => {
      release([{ day: "2026-10-25", energy_kwh: 2 }]);
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(result.current.loading).toBe(false);
    expect(result.current.daily.data).toEqual([{ day: "2026-10-25", energy_kwh: 2 }]);
  });
});
