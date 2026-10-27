# WindIQ

**Live-Ertragsrechnung** für eine Windenergieanlage. Die Anwendung holt laufend stündliche
Messwerte vom WindIQ-Messmast, bereinigt und speichert sie in PostgreSQL und berechnet daraus
den Jahresertrag: AEP brutto und netto, P50 und P90. Ein Dashboard zeigt die Ergebnisse und
aktualisiert sich selbst.

Das Dashboard ist auf Deutsch, Code und API sind auf Englisch (siehe [terminology.md](docs/terminology.md)).

**Stack:** FastAPI · PostgreSQL 17 · SQLAlchemy · Alembic · taskiq · React · TypeScript · Vite · Recharts · Docker

## Funktionsweise

```
                  Cron alle 5 Min. · Button „Winddaten abrufen“
                                 │
WindIQ API ──▶ Worker ──Upsert──▶ PostgreSQL ──SQL-Views──▶ Backend (FastAPI) ──▶ Dashboard (React, nginx)
```

1. **Ingest.** Der Worker holt alle 5 Minuten sowie auf Anstoß neue und geänderte Messwerte ab.
   Er rechnet Zeitstempel nach UTC und km/h nach m/s um und markiert jede Stunde als `ok`,
   `suspect`, `missing` oder `malformed`. Die Rohwerte bleiben zur Nachvollziehbarkeit erhalten.
2. **Speichern.** Eine Zeile pro Stunde. Eine korrigierte Revision aus der API ersetzt die ältere.
3. **Berechnen.** SQL-Views rechnen die Windgeschwindigkeit auf die Nabenhöhe um, lesen die
   Leistungskennlinie aus und summieren zu Tages- und Jahresenergie. Verdächtige, fehlende und
   fehlerhafte Stunden liefern keinen Ertrag; sie erscheinen als Lücke in der Datenabdeckung.
4. **Anzeigen.** Das Dashboard zeigt P50 und P90, AEP brutto und netto, Tagesenergie, Windrose,
   Wind der letzten 48 Stunden, Datenalter und Abdeckung sowie den Ingest-Verlauf.

### Berechnung

Die Berechnung:

- Der Mast misst tiefer als die Nabe: `v_Nabe = v_Mess × (h_Nabe / h_Mess) ^ α`, mit α als Windgradient (Höhenexponent)
- AEP brutto: Energie laut Leistungskennlinie über die letzten 12 Monate, in MWh
- AEP netto = AEP brutto × (1 − Verfügbarkeit) × (1 − elektrisch) × (1 − Abschattung)
- P50 = AEP netto
- P90 = P50 × (1 − 1,282 × U), mit U als Unsicherheit

## Schnellstart

Entwicklungsumgebung mit Hot Reload:

```sh
cp backend/.env.example backend/.env    # WIQ_CLIENT_ID und WIQ_CLIENT_SECRET eintragen
docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build
```

Dashboard: http://localhost:5173 · API-Doku: http://localhost:5173/api/docs

`docker compose up --build` startet den produktionsnahen Stack auf http://localhost:8080.
Die WindIQ-Zugangsdaten werden an Backend, Worker und Scheduler darin noch nicht übergeben.
Für die lokale Arbeit daher das Dev-Overlay nutzen. Details: [operations.md](docs/operations.md#configuration).

**Deployment:** Die Produktions-Images baut GitHub Actions, Coolify auf einem VPS zieht sie.
Details: [operations.md](docs/operations.md#deploy).

## Dokumentation

Die Dokumente im Ordner `docs/` sind auf Englisch.

| Dokument | Inhalt |
| --- | --- |
| [decisions.md](docs/decisions.md) | Warum das System so gebaut ist |
| [operations.md](docs/operations.md) | Konfiguration, Health-Checks, Lauf-Verfolgung, Backups, Deployment, Rollback |
| [development.md](docs/development.md) | Entwicklungsumgebung, Tests, Migrationen, Client-Generierung, API-Endpunkte, Struktur |
| [ingest-strategy.md](docs/ingest-strategy.md) | Ingest-Auslöser, Normalisierung, QC-Regeln, geschützte Upserts |
| [resilience.md](docs/resilience.md) | Prozessrollen, Fehlerfälle und Wiederanlauf |
| [api-measurements-quirks.md](docs/api-measurements-quirks.md) | Datenqualität der WindIQ-Messwert-API |
| [terminology.md](docs/terminology.md) | Deutsche UI-Begriffe und ihre englischen Entsprechungen |
| [implementation-plan.md](docs/implementation-plan.md) | Bauphasen, Abnahmekriterien, Zeitbudget |

## Status

Alle fünf Phasen des [Implementierungsplans](docs/implementation-plan.md) sind abgeschlossen:
Persistenz, Ingest, API, Dashboard und Betrieb. Ein voller Backfill eines Jahres Messwerte
dauert etwa 8 Sekunden.
