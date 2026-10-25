# WindIQ

Jahresertragsrechnung für eine Windenergieanlage: Die Anwendung holt stündliche
Messwerte vom WindIQ-Messmast aus der Measurement-API, speichert sie in Postgres
und berechnet daraus den Jahresertrag (AEP brutto/netto, P50, P90). Das Dashboard
(React-SPA) zeigt das Ergebnis live.

## Funktionsweise

```
WindIQ API ──Ingest-Worker (FastAPI)──▶ Postgres ──/api/*──▶ React-SPA (nginx)
```

1. **Stammdaten**: Mast, Anlage (mit Leistungskennlinie) und Standortparameter
   werden bei jedem Sync in der DB aktualisiert (über `updated_at` geschützt).
2. **Messwerte**: Werte kommen stündlich; beim Ingest wird normalisiert:
   Zeitzonen → UTC, km/h → m/s. QC-Flags markieren fehlende und unplausible Werte.
3. **Aggregate**: SQL-Views: Leistung aus der Kennlinie auf Nabenhöhe, Tagessummen,
   AEP über die letzten 12 Monate brutto und netto, P50 und P90.
4. **Dashboard**: Ergebniswerte, Diagramme und der Datenstatus (letzter
   Ingest-Lauf, Abdeckung). Die SPA aktualisiert sich per Polling alle 60 s.

Formeln (Case Study): `v_Nabe = v_Mess · (h_Nabe / h_Mess)^α` ·
AEP netto = AEP brutto × (1 − Verfügbarkeit) × (1 − elektrisch) × (1 − Abschattung) ·
P90 = P50 × (1 − 1,282 × U). Suspect/missing-Stunden zählen **nicht** zur Energie.

Status: Persistenz-Layer (Phase 1) und Ingest-Worker (Phase 2) vollständig —
Voll-Backfill in ~8 s, idempotent, QC/Journal live. Phasenplan und Abnahmekriterien:
[docs/implementation-plan.md](docs/implementation-plan.md).

## Quickstart

```sh
docker compose up --build
```

- **App:** http://localhost:8080 — nginx liefert das React-Bundle und leitet `/api/*` an das Backend weiter
- **API health:** http://localhost:8080/api/health
- **Swagger:** http://localhost:8080/api/docs

Das Backend ist vom Host aus nicht direkt erreichbar; der gesamte Traffic läuft über nginx.

Datenbankzugriff:

```sh
docker compose exec db psql -U windiq
```

## Entwicklung (Hot Reload, ohne Docker)

```sh
# Terminal 1 — DB + API auf http://localhost:8000
docker compose up -d db
cd backend && uv sync && uv run alembic upgrade head
uv run uvicorn app.main:app --reload

# Terminal 2 — UI auf http://localhost:5173
cd frontend && npm install && npm run dev
```

Vite leitet `/api/*` an das Backend weiter, wie in Produktion.

Env-Dateien: `backend/.env` (siehe `backend/.env.example`) mit `WIQ_CLIENT_ID`,
`WIQ_CLIENT_SECRET`, `WIQ_API_BASE_URL` und `DATABASE_URL`.

## CI/CD (GitHub Actions → Coolify)

- **CI** (`.github/workflows/ci.yml`): Frontend-Typcheck + Build, Backend-Tests
  (mit Postgres-Service-Container), Build beider Docker-Images.
- **Deploy** (`.github/workflows/deploy.yml`): Push nach `main` → Images nach GHCR →
  Coolify-Webhook zieht die Bilder (Compose am VPS). Rollback: Image-Tag im
  `docker-compose.prod.yml` pinnen.
- Das `db`-Volume bleibt bei Rebuilds erhalten; Schema-Änderungen laufen über
  Alembic-Migrationen.

## Struktur

```
frontend/                     React + TS + Vite · multi-stage Dockerfile → nginx
  nginx.conf                    gzip · Asset-Caching · /api-Proxy · SPA-Fallback
backend/
  app/main.py                   FastAPI-App, /api/health, /api docs
  app/windiq/                   Client-Fassade für die WindIQ-API (auth, retry)
  app/db/                       SQLAlchemy-async-Modelle, Repo, Alembic
  app/ingest/                   Ingest-Worker: Backfill, Taktlauf, QC
  packages/windiq_client/       autogenerierter OpenAPI-Client — bitte nicht von Hand
                                editieren; neu erzeugen mit `uv run scripts/generate-client.sh`
  tests/                        pytest (inkl. Postgres-Integrationstests)
docs/                          Case Study (PDF), Implementierungsplan
```

---

## Decisions

Wichtige Entscheidungen mit Datum und Grund (Datenbasis: Sondierung der API, siehe Findings):

| # | Datum | Entscheidung | Grund |
| --- | --- | --- | --- |
| 1 | 2026-10-25 | Postgres 17 + SQLAlchemy 2.0 (async) + asyncpg + Alembic | Volle Async-Pipeline ist gefordert; SQLAlchemy-async ist der stabilste Weg, Alembic hält das Schema versioniert |
| 2 | 2026-10-25 | `measurements`-Tabelle — eine Zeile pro Messstunde, neueste Version gewinnt | Die API meldet Korrekturen als neue Version; für die Ertragsrechnung zählt nur der neueste Stand, `version`/`updated_at` dokumentieren den Verlauf |
| 3 | 2026-10-25 | Kanonisierung beim Ingest: UTC-Schlüssel (`timestamptz`), m/s | Die API liefert gemischte Einheiten und verschiedene Zeitzonen-Suffixe; Kanonisierung macht Upsert, Idempotenz und Indizes sauber |
| 4 | 2026-10-25 | QC-Flag plus Rohwert in derselben Zeile | Die API liefert `null`, Textwerte wie „7.47“ und Ausreißer; mit Rohwert und Flag bleibt die Bereinigung nachvollziehbar |
| 5 | 2026-10-25 | Suspect/missing-Stunden liefern **keinen** Ertrag | Fehlende oder unplausible Stunden erscheinen in der Abdeckung, statt die Ertragszahl zu verfälschen |
| 6 | 2026-10-25 | Plain SQL-Views, keine materialisierten Rollups | Bei 8,7k Zeilen/Jahr ist die Aggregation je Abfrage schnell; kein Refresh-Takt, keine Wartung |
| 7 | 2026-10-25 | Ingest im Backend als asyncio-Task (lifespan), kein separater Container | Kleines Deployment, keine Queue; eine spätere Auslagerung bleibt einfach |
| 8 | 2026-10-25 | Sync über `updated_since`-Wasserzeichen mit 1 h Overlap | Die API beantwortet die Änderungszeit-Abfrage korrekt; der Overlap sichert späte Revisionen ab, Replay bleibt durch idempotente Upserts harmlos |
| 9 | 2026-10-25 | Kein TimescaleDB, keine Partitionierung | Volumen unter 1 MB/Jahr; Zeitserien-Features wären hier Overhead |

## Findings

Erneute Sondierung s. [docs/api-measurements-quirks.md](docs/api-measurements-quirks.md) —
die API liefert ein **gleitendes 1-Jahres-Fenster**; die Zahlen hier sind damit historisch.

Sondierung der API-Daten: ein vollständiges Jahr, 8.704 Zeilen in 18 Pages (limit 500).
Stand der Sondierung: 2026-10-25, über die Client-Fassade (`app/windiq/client.py`).

| Beobachtung | Detail | Konsequenz |
| --- | --- | --- |
| Korrekturen sind real | `version` 1→2→3; `updated_at` teils 4 Tage nach Messzeit | Neueste-Version-Upsert (#2, #8) |
| `updated_since` liefert zuverlässig nur geänderte Zeilen | sortiert nach Änderungszeit | Taktlauf per Änderungs-Wasserzeichen statt Vollscan |
| Zeitzonen-Varianten in `timestamp` | `Z` (7.965), `+02:00` (720), `+00:00` (19); die 19 `+00:00`-Einträge verdoppeln UTC-Stunden, die es auch als `Z` gibt | UTC-Normalisierung als Bestandteil des Primärschlüssels (#3) |
| Einheitenwechsel | m/s: 8.355 · km/h: 349 (Dezember 2025) | Einheit normalisieren (#3), `unit` trotzdem halten (#4) |
| Malformed-Values | 30× `null` · 34× Zahlen als Text („7.47") · Sentinel `−999.0` (unter den 58 negativen Werten) · max. 83 m/s (cut-out liegt bei 25) | QC-Flags `suspect`/`missing`/`malformed` (#4, #5) |
| Fehlende Stunden | ca. 75 fehlende Stunden im Jahr, u. a. eine 47-h-Lücke | Abdeckungsstatistik statt Befüllung (#5) |
| Volumen | ~8,7 k Zeilen ≈ <1 MB/Jahr | Eine einfache Postgres-Tabelle reicht (#6, #9) |
| Paginierung | `limit ≤ 500`, stabile Cursor | Backfill mit `since`, 18 Pages |
| Stammdaten ändern sich gelegentlich | Turbine `version` 43, Site `version` 44, jeweils mit `updated_at` | Stammdaten in der DB mit Upsert-Guard statt Config |

Details und Umsetzungsschritte in [docs/implementation-plan.md](docs/implementation-plan.md).
