/** App-level integration: skeleton gate + progress bar during boot, then the
 * real dashboard; per-panel refresh dimming. */
import { act, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import App from "./App";
import { metrics, showTab, stubDashboardFetch } from "./test/helpers";

let responses: ReturnType<typeof stubDashboardFetch>["responses"];
let fetchMock: ReturnType<typeof stubDashboardFetch>["fetchMock"];

function renderApp() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.useFakeTimers();
  showTab();
  ({ responses, fetchMock } = stubDashboardFetch());
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe("App", () => {
  it("shows the skeleton and an active progress bar during boot, then the dashboard", async () => {
    let release!: (value: unknown) => void;
    responses["/api/metrics"] = new Promise((resolve) => {
      release = resolve;
    });

    const { container } = renderApp();
    expect(container.querySelector(".dashboard")).toBeNull();
    expect(container.querySelector(".progress.active")).not.toBeNull();

    await act(async () => {
      release(metrics);
      await vi.advanceTimersByTimeAsync(0);
    });

    expect(container.querySelector(".dashboard")).not.toBeNull();
    expect(container.querySelector(".progress.active")).toBeNull();
  });

  it("dims a panel while its refresh is in flight", async () => {
    const { container } = renderApp();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(container.querySelector(".data.refreshing")).toBeNull();

    let release!: (value: unknown) => void;
    responses["/api/metrics"] = new Promise((resolve) => {
      release = resolve;
    });

    // the masthead refresh button is the only manual trigger on the page
    const button = container.querySelector<HTMLButtonElement>(".masthead button");
    expect(button?.textContent).toBe("Aktualisieren");
    await act(async () => {
      button?.click();
      await vi.advanceTimersByTimeAsync(0);
    });

    expect(container.querySelector(".data.refreshing")).not.toBeNull();
    expect(container.querySelector(".progress.active")).not.toBeNull();
    expect(button?.textContent).toBe("Aktualisiere…");

    await act(async () => {
      release(metrics);
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(container.querySelector(".data.refreshing")).toBeNull();
  });

  it("refetches the wind series when range or resolution changes", async () => {
    renderApp();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(fetchMock).toHaveBeenCalledWith("/api/wind?days=2&resolution=hour", expect.anything());

    await act(async () => {
      screen.getByRole("button", { name: "7 d" }).click();
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(fetchMock).toHaveBeenCalledWith("/api/wind?days=7&resolution=hour", expect.anything());

    await act(async () => {
      screen.getByRole("button", { name: "Täglich" }).click();
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(fetchMock).toHaveBeenCalledWith("/api/wind?days=7&resolution=day", expect.anything());
  });
});
