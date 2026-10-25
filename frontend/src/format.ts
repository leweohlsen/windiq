/** Shared display formatting — German presentation per docs/terminology.md:
 * de-DE numbers (decimal comma), dates and datetimes; units stay m/s, kWh,
 * MWh, GWh, h, d (valid unit symbols in German). */

const nf = (decimals: number) =>
  new Intl.NumberFormat("de-DE", {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });

/** Trailing 12 months → GWh, fixed decimals. */
export const asGWh = (kwh: number | null, decimals = 2) =>
  kwh == null ? "–" : nf(decimals).format(kwh / 1e6);

/** Daily energies → MWh, fixed decimals. */
export const asMWh = (kwh: number | null, decimals = 1) =>
  kwh == null ? "–" : nf(decimals).format(kwh / 1000);

export const asMs = (value: number | null, decimals = 1) =>
  value == null ? "–" : nf(decimals).format(value);

/** Plain number without a unit (shear exponent, heights): 0.2 → "0,2". */
export const asNum = (value: number | null | undefined, decimals = 2) =>
  value == null
    ? "–"
    : new Intl.NumberFormat("de-DE", { maximumFractionDigits: decimals })
        .format(value);

export const asHours = (value: number | null) =>
  value == null ? "–" : nf(0).format(value);

/** Share in percent without the sign — callers append the spaced " %". */
export const asPercent = (part: number, whole: number, decimals = 1) =>
  whole > 0 ? nf(decimals).format((part / whole) * 100) : "0,0";

export const asDate = (iso: string | null) =>
  iso == null ? "–" : new Date(iso).toLocaleDateString("de-DE");

export const asDateRange = (from: string | null, to: string | null) =>
  `${asDate(from)} – ${asDate(to)}`;

export const asClock = (iso: string | null) =>
  iso == null ? "–" : new Date(iso).toLocaleString("de-DE");

/** Duration between two run timestamps → "4,2 s" / "2 Min. 10 s" / "1 h 5 Min.". */
export const asDuration = (from: string | null, to: string | null) => {
  if (from == null || to == null) return "–";
  const seconds = (new Date(to).getTime() - new Date(from).getTime()) / 1000;
  if (Number.isNaN(seconds) || seconds < 0) return "–";
  if (seconds < 60) return `${nf(1).format(seconds)} s`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes} Min. ${Math.round(seconds % 60)} s`;
  const hours = Math.floor(minutes / 60);
  return `${hours} h ${minutes % 60} Min.`;
};

export const asAge = (seconds: number | null) => {
  if (seconds == null) return "unbekannt";
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes} min`;
  const hours = Math.floor(minutes / 60);
  if (hours < 48) return `${hours} h ${minutes % 60} min`;
  return `${Math.floor(hours / 24)} d`;
};

/** Run status → German display text; pill CSS classes keep the raw value. */
const STATUS_DE: Record<string, string> = {
  ok: "ok",
  partial: "teilweise",
  error: "Fehler",
};
export const asStatus = (status: string) => STATUS_DE[status] ?? status;
