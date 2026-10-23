# Atlas

An ontology platform applied to disaster response. It pulls live
earthquake (USGS) and weather-alert (NWS) feeds into a typed ontology of linked objects
and serves them through a generic, schema-driven API.

## Architecture

```
connectors → data/landing/ → DuckDB pipelines → indexer → Postgres object store ← API (any number) ← web app
└──────────────────── atlas worker (the only writer) ──────────────────┘          └─ atlas serve (read-only)
```

DuckDB is the pipeline engine (raw → clean datasets). The **indexer** loads those datasets into a
Postgres **object store** shaped by `ontology/ontology.yaml`: one table per object type and link,
rebuilt in a staging schema and swapped live atomically. The API only reads Postgres, so it holds no
lock on the pipeline and can run as many instances as needed.

## Setup

```bash
brew install postgresql@17 && brew services start postgresql@17   # once
createdb atlas                                                      # once
uv sync
```

## Running

```bash
uv run atlas sync       # one cycle: pull sources → rebuild datasets → index objects into Postgres
uv run atlas worker     # the same cycle every 5 min (--every SECONDS); leave it running
uv run atlas serve      # API + web app on http://127.0.0.1:8000 (API docs at /docs)
```

Run `worker` and `serve` in separate terminals. Other commands:

```bash
uv run atlas index      # rebuild datasets and re-index from what's already landed (no network)
uv run atlas validate   # check ontology.yaml against the clean datasets
uv run pytest           # parity tests: DuckDB and Postgres backends must answer identically
```

**Settings:** `DATABASE_URL` (default `postgresql://localhost/atlas`). Set `ATLAS_OBJECT_STORE=duckdb`
to serve straight from the DuckDB datasets with no Postgres. That mode is for offline use: run
`atlas sync` first, and don't run a worker alongside it.

**Inspecting the data:** `psql atlas` (the object store is in schema `ontology`; every sync is logged in
`atlas_meta.sync_runs`), or `duckdb -ui data/atlas.duckdb` for the pipeline datasets. The worker only
opens the DuckDB file during a sync, so the file is free between runs.

## Web app

```bash
cd web && npm install && npm run build   # builds web/dist, which `atlas serve` serves at /
cd web && npm run dev                    # or develop with hot reload on :5173 (proxies /api to :8000)
```

- **Operating picture:** a live map of counties shaded by their worst active alert, with earthquakes sized by
  magnitude. A side panel shows KPIs, earthquakes over time, hotspots (counties with both a recent quake and an
  active alert) and alerts by type. Click anything on the map to open it as an object and follow its links.
- **Object explorer:** a generic browser over every object type in the ontology: search, sort, page, then
  follow links from object to object. Nothing in it is specific to earthquakes or alerts.

## How it fits together

| Layer | Where | What it does |
| --- | --- | --- |
| Connectors + landing zone | `src/atlas/connectors/`, `data/landing/` | Pull each source and keep its raw snapshots untouched |
| Pipelines | `src/atlas/pipelines/transforms/*.sql` | Clean, deduplicate and link the raw data into datasets |
| Ontology | `ontology/ontology.yaml`, `src/atlas/ontology/registry.py` | Define object types, properties and links over the datasets |
| Indexer + object store | `src/atlas/index/`, Postgres schema `ontology` | Load the datasets into Postgres, shaped by the ontology |
| Object sets (query compilation) | `src/atlas/ontology/store.py`, `backends.py` | Turn filters and link traversals into SQL |
| Ontology API (objects, links, object sets, aggregations) | `src/atlas/api.py` | Generic, schema-driven access to every object type |
| Web app | `web/` | Live operating picture and object explorer |

## API examples

```bash
curl 'localhost:8000/api/objects/Earthquake?magnitude.gte=4&order_by=magnitude&desc=true'
curl localhost:8000/api/objects/County/06029/links/weatherAlerts
curl -X POST localhost:8000/api/objectSets/load -H 'content-type: application/json' -d '{
  "object_type": "Earthquake",
  "steps": [
    {"where": {"property": "magnitude", "op": "gte", "value": 2.5}},
    {"search_around": "county"},
    {"search_around": "weatherAlerts"}
  ]
}'
```

Filters use `<property>.<op>=<value>` with ops `eq ne gt gte lt lte contains is_null is_not_null`.
