import { describe, expect, it } from "vitest";

import {
  asAge,
  asClock,
  asDate,
  asDateRange,
  asDuration,
  asHours,
  asMs,
  asMWh,
  asNum,
  asPercent,
  asStatus,
} from "./format";

describe("asMWh / asMs / asNum / asHours", () => {
  it("formats de-DE with decimal comma and thousands dot", () => {
    expect(asMWh(7_398_000, 0)).toBe("7.398");
    expect(asMWh(1_234_500, 1)).toBe("1.234,5");
    expect(asMs(7.47)).toBe("7,5");
    expect(asHours(8585)).toBe("8.585");
    expect(asNum(0.2)).toBe("0,2");
  });

  it("renders a dash for missing values", () => {
    expect(asMWh(null)).toBe("–");
    expect(asMs(null)).toBe("–");
    expect(asNum(undefined)).toBe("–");
    expect(asHours(null)).toBe("–");
  });
});

describe("asPercent", () => {
  it("formats shares with a decimal comma", () => {
    expect(asPercent(8580, 8760)).toBe("97,9");
  });

  it("returns 0 instead of dividing by zero", () => {
    expect(asPercent(1, 0)).toBe("0,0");
  });
});

describe("asDuration", () => {
  it("formats seconds, minutes and hours", () => {
    expect(asDuration("2026-01-01T00:00:00Z", "2026-01-01T00:00:01.4Z")).toBe("1,4 s");
    expect(asDuration("2026-01-01T00:00:00Z", "2026-01-01T00:01:40Z")).toBe("1 Min. 40 s");
    expect(asDuration("2026-01-01T00:00:00Z", "2026-01-01T01:05:00Z")).toBe("1 h 5 Min.");
  });

  it("renders a dash for open ends or invalid ranges", () => {
    expect(asDuration("2026-01-01T00:00:00Z", null)).toBe("–");
    expect(asDuration("2026-01-01T01:00:00Z", "2026-01-01T00:00:00Z")).toBe("–");
  });
});

describe("asAge", () => {
  it("formats minutes, hours and days", () => {
    expect(asAge(35 * 60)).toBe("35 min");
    expect(asAge(90 * 60)).toBe("1 h 30 min");
    expect(asAge(72 * 3600)).toBe("3 d");
  });

  it("renders unknown when there is no data age", () => {
    expect(asAge(null)).toBe("unbekannt");
  });
});

describe("dates", () => {
  // noon UTC keeps the calendar day stable in every realistic timezone
  const noon = "2026-10-26T12:00:00Z";

  it("formats German dates and ranges", () => {
    expect(asDate(noon)).toBe("26.10.2026");
    expect(asDateRange(noon, "2025-10-26T12:00:00Z")).toBe("26.10.2026 – 26.10.2025");
    expect(asDateRange(null, null)).toBe("– – –");
    expect(asClock(noon)).toContain("26.10.2026");
  });
});

describe("asStatus", () => {
  it("maps known statuses to German and passes unknown through", () => {
    expect(asStatus("ok")).toBe("ok");
    expect(asStatus("partial")).toBe("teilweise");
    expect(asStatus("error")).toBe("Fehler");
    expect(asStatus("mystery")).toBe("mystery");
  });
});
