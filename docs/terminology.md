# Terminology: German UI presentation

The backend (code, API fields, DB) stays **English**; the frontend presents in
**German**. This document is the binding mapping between the two. Sources:

- **Vorgabe** — the project assignment: section "So wird der Ertrag berechnet"
  and the endpoint table (authoritative for domain terms).
- **API** — German field descriptions shipped in the generated client
  (`wind_iq_measurement_api_client`), e.g. "Höhenexponent α für die
  Höhenumrechnung".
- **Domain** — standard German wind-energy usage, for terms the assignment does not name.

Rule of thumb: translate what the user reads; keep technical loanwords that are
standard in German tech language (AEP, P50/P90, Ingest, QC, m/s, kWh/MWh).

## 1. Domain terms (assignment vocabulary)

| Backend / API (EN) | UI (DE) | Source | Note |
|---|---|---|---|
| site | Standort | Vorgabe | |
| mast / measurement mast | Messmast | Vorgabe | |
| measurement height | Messhöhe | Vorgabe | |
| turbine | Windenergieanlage | Vorgabe | |
| hub height | Nabenhöhe | Vorgabe | |
| shear exponent α | Windgradient α | Vorgabe | Vorgabe endpoint table says "Windgradient"; API client says "Höhenexponent α". Use **Windgradient (Höhenexponent) α** in the methodology table — see §6 |
| power curve | Leistungskennlinie | Vorgabe | |
| measurements | Messwerte | Vorgabe | |
| AEP gross | AEP brutto | Vorgabe | |
| AEP net | AEP netto | Vorgabe | |
| availability loss | Verfügbarkeitsverlust | Vorgabe ("Verfügbarkeit") | |
| electrical loss | elektrische Verluste | Vorgabe ("elektrisch") | |
| wake loss | Abschattungsverlust | Vorgabe ("Abschattung") | Standard wind term would be "Nachlaufverlust", but the assignment defines this factor as "Abschattung" — follow the assignment |
| uncertainty U | Unsicherheit U | Vorgabe | |
| P50 / P90 | P50 / P90 | Vorgabe | untranslated |
| annual energy yield / revenue | Ertrag / Jahresertrag | Vorgabe | "Live-Ertragsrechnung" is the assignment's name for the whole app |

## 2. Wind & time-series terms

| Backend (EN) | UI (DE) | Source |
|---|---|---|
| wind speed | Windgeschwindigkeit | Domain |
| wind direction | Windrichtung | Domain |
| wind rose | Windrose | Domain |
| mean wind | mittlere Windgeschwindigkeit | Domain |
| daily energy | Tagesenergie | Domain |
| trailing 12 months | letzte 12 Monate | Domain |
| trailing 30 days | letzte 30 Tage | Domain |
| measurement range | Messzeitraum | Domain |

## 3. QC categories

Backend quality values (`ok`, `suspect`, `missing`, `malformed`) are **not
translated in data**, only in labels:

| Backend value | UI (DE) | Meaning |
|---|---|---|
| ok | ok | verwertbare Stunde |
| suspect | verdächtig | unplausibel, aber im Toleranzbereich |
| missing | kein Wert | No-data-Sentinel (−999) |
| malformed | fehlerhaft | nicht parsbar / falsche Form |
| absent (no row at all) | nicht geliefert | Fehlzeit im erwarteten Zeitraum |

"Usable hours" (ok hours) → **verwertbare Stunden**.

## 4. Ingest & operations

| Backend (EN) | UI (DE) | Note |
|---|---|---|
| ingest run | Ingest-Lauf | "Ingest" stays (common German tech loanword) |
| ingest history | Ingest-Verlauf | |
| last ingest run | Letzter Ingest-Lauf | |
| sync now | Winddaten abrufen | |
| queued… | in Warteschlange… | |
| pages | Seiten | |
| inserted / updated | neu / geändert | table column: "Zeilen (neu/geändert)" |
| max gap | maximale Lücke | |
| data coverage | Datenabdeckung | |
| data age | Datenalter | |
| stale | veraltet | |
| detail | Details | |
| QC totals | QC-Statistik | |

## 5. UI strings per component

| Component | Current (EN) | German |
|---|---|---|
| App | Refresh / Refreshing… | Aktualisieren / Aktualisiere… |
| App | Wind | Wind |
| App | Data status | Datenstatus |
| App | Ingest history | Ingest-Verlauf |
| App | Methodology | Berechnungsmethode |
| App | Loading… / No data. / Retry / Failed to load — | Laden… / Keine Daten. / Erneut versuchen / Laden fehlgeschlagen — |
| App | Last refresh failed — showing previous data. | Letzte Aktualisierung fehlgeschlagen — es werden die letzten Daten angezeigt. |
| App | values refresh every 60 s | Werte aktualisieren sich alle 60 s |
| Header | No reference data yet | Noch keine Referenzdaten |
| Header | P50 · trailing 12 months | P50 · letzte 12 Monate |
| Header | AEP gross / AEP net | AEP brutto / AEP netto |
| Header | Measurement range | Messzeitraum |
| Header | Usable hours | Verwertbare Stunden |
| Header | hub 140 m / mast 100 m | Nabe 140 m / Mast 100 m |
| DailyChart | Daily energy (90 days) | Tagesenergie (90 Tage) |
| DailyChart | Daily energy (legend) | Tagesenergie |
| DailyChart | Mean wind (m/s) | Mittlere Windgeschwindigkeit (m/s) |
| DailyChart | Energy: / Mean wind: / max | Energie: / Mittlerer Wind: / max |
| DailyChart | Ok hours: 21/24 | Verwertbare Stunden: 21/24 |
| WindPanel | Wind rose — … ok hours · trailing 30 days | Windrose — … verwertbare Stunden · letzte 30 Tage |
| WindPanel | Wind speed — last 48 h (mast height) | Windgeschwindigkeit — letzte {days} Tage, {stündlich\|täglich\|wöchentlich} (Messhöhe) |
| WindPanel | Range switch (2/7/30/90/365 d) | Bereichsschalter (2/7/30/90/365 Tage) |
| WindPanel | Resolution switch | Auflösungsschalter (Stündlich / Täglich / Wöchentlich) |
| WindPanel | Mean wind (m/s) (legend) | Mittel (m/s) |
| WindPanel | QC bars (legend) | Verdächtig / Ohne Wert / Fehlerhaft |
| WindPanel | Mittel: x m/s · Min / Max (Originalwerte): y / z m/s | Mittel: x m/s · Min / Max (Originalwerte): y / z m/s |
| WindPanel | QC: a verdächtig · b ohne Wert · c fehlerhaft | QC: a verdächtig · b ohne Wert · c fehlerhaft |
| WindPanel | Ok hours: / Mean speed: | Verwertbare Stunden: / Mittlere Geschwindigkeit: |
| WindPanel | (clockwise) | (im Uhrzeigersinn) |
| WindPanel | Brush strip (drag to zoom) | Auswahlstreifen (ziehen zum Zoomen) |
| WindPanel | Reset zoom | Zoom zurücksetzen |
| DataStatus | Last ingest run | Letzter Ingest-Lauf |
| DataStatus | Finished at: … · duration … | Abgeschlossen: … · Dauer … |
| DataStatus | Pages 3 · 100 inserted · 5 updated | Seiten 3 · 100 neu · 5 geändert |
| DataStatus | QC of that run: … missing · … suspect · … malformed | QC des Laufs: … ohne Wert · … verdächtig · … fehlerhaft |
| DataStatus | No ingest run recorded yet. | Noch kein Ingest-Lauf aufgezeichnet. |
| DataStatus | Data age: / (stale) | Datenalter: / (veraltet) |
| DataStatus | Coverage: 98.2% (… of … h) | Abdeckung: 98,2 % (… von … h) |
| DataStatus | QC totals: … absent · … missing · … suspect · … malformed | QC-Statistik: … nicht geliefert · … ohne Wert · … verdächtig · … fehlerhaft |
| DataStatus | Max gap: … h within the trailing 12 months | Maximale Lücke: … h innerhalb der letzten 12 Monate |
| DataStatus | Queueing failed — retry later. | Einreihung fehlgeschlagen — bitte später erneut versuchen. |
| IngestHistory | Started / Status / Duration / Pages | Gestartet / Status / Dauer / Seiten |
| IngestHistory | Rows (ins/upd) | Zeilen (neu/geändert) |
| IngestHistory | QC (miss/susp/malf) | QC (o.W./verd./fehler) |
| IngestHistory | Max gap / Detail | Maximale Lücke / Details |
| IngestHistory | No ingest run recorded yet. | Noch kein Ingest-Lauf aufgezeichnet. |
| Methodology | Factor / Value / From | Faktor / Wert / Quelle |
| Methodology | Shear exponent α | Windgradient (Höhenexponent) α |
| Methodology | Availability loss / Electrical loss / Wake loss | Verfügbarkeitsverlust / elektrische Verluste / Abschattungsverlust |
| Methodology | Uncertainty U / Hub height / Mast height | Unsicherheit U / Nabenhöhe / Messhöhe |
| Methodology | methodology paragraph | text per assignment "So wird der Ertrag berechnet", keeping the formulas symbolic (v_Nabe, AEP brutto/netto, P50, P90) |

## 6. Formatting conventions

- Numbers: `de-DE` locale (decimal comma, `.` thousands) — `asMWh`,
  `asMs`, `asPercent`, `asHours` switch to `Intl.NumberFormat("de-DE")`.
  Percent sign with a space: `98,2 %`.
- Dates: `de-DE` — `25.10.2026`; datetimes `25.10.2026, 14:00`.
  Replaces the hardcoded `en-US` in `format.ts` (`asDate`, `asClock`),
  `DailyChart` tooltip and `WindPanel` X-axis.
- Units: `m/s`, `kWh`, `MWh`, `h`. Annual values (AEP brutto/netto, P50, P90) are shown
  in MWh, as the assignment specifies.

## 7. Decisions to keep in mind

1. **Compass letters:** the rose keeps the international `N/NE/E/…` from the
   backend (`repo.COMPASS`). German `O` (Ost) is not introduced — international
   abbreviations are standard on German wind/marine charts. If German letters
   are wanted, only `WindPanel.tsx` and the backend constant would change.
2. **Run status pills:** backend statuses `ok` / `partial` / `error` are shown
   verbatim inside `pill-*` spans. Translate the display text only
   (ok / teilweise / Fehler) while keeping the CSS class from the raw value.
3. **Windgradient vs. Höhenexponent:** assignment and API client disagree. UI label is
   "Windgradient (Höhenexponent) α" so both sources are recognizable; the α
   symbol disambiguates.
