# Atlas

An ontology platform applied to disaster response. It pulls live hazard feeds and
reference data into a typed ontology of linked objects (counties, earthquakes, weather
alerts, fires, facilities) and serves them through a generic, schema-driven API.

## Data sources

| Source | Object | Refresh | Key |
| --- | --- | --- | --- |
| [USGS earthquake feed](https://earthquake.usgs.gov/earthquakes/feed/) | Earthquake | every sync (5 min) | none |
| [NWS active alerts](https://www.weather.gov/documentation/services-web-api) | WeatherAlert | every sync | none |
| [NASA FIRMS](https://firms.modaps.eosdis.nasa.gov/) (VIIRS) | FireDetection | every sync, last 7 days kept | `NASA_FIRMS_API_KEY` (free) |
| [OpenStreetMap](https://www.openstreetmap.org/) extracts from [Geofabrik](https://download.geofabrik.de/) | Facility (hospitals, shelters, fire stations, schools) | weekly, in the background (daily diffs applied) | none |
| Census gazetteer, county boundaries, 2024 population estimates | County | once | none |

Facility data © OpenStreetMap contributors, available under the
[Open Database License](https://www.openstreetmap.org/copyright); extracts by Geofabrik GmbH.

**How facilities are built:** the first run downloads the Geofabrik US extract (~12 GB, verified by MD5)
plus Puerto Rico into `data/osm/`. Each weekly refresh applies Geofabrik's daily change files to it
(`pyosmium-up-to-date`, minutes) instead of re-downloading. `osmium tags-filter` then keeps only
facility tags (a few MB), and `osmium export` writes them as GeoJSON lines for the pipeline.

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

Atlas runs the same way on macOS and in a Linux container.

**macOS:**

```bash
brew install postgresql@17 osmium-tool && brew services start postgresql@17   # once
createdb atlas                                                                  # once
uv sync
```

**Linux container** (Postgres, the worker and the API, with data on a volume):

```bash
docker compose up --build        # web app + API on http://localhost:8000
```

The image installs `osmium-tool` from apt and bakes in DuckDB's spatial extension. `docker build
--target test .` runs the test suite on Linux.

**Disk:** about 13 GB for the full US extract under `ATLAS_DATA_DIR` (default `./data`; `/data` in the
container). To try facilities small, e.g. on a laptop, use one state:
`ATLAS_OSM_REGIONS=north-america/us/rhode-island` (52 MB, seconds). The first full-US run downloads
12 GB, so it's best done in the container.

Fire detections need a free NASA FIRMS key ([request one](https://firms.modaps.eosdis.nasa.gov/api/map_key/)).
Put it in a `.env` file in the project root or `src/atlas/`: `NASA_FIRMS_API_KEY=...`. `.env` files are
git-ignored; never commit a key. Without one, everything else works and fires are skipped. FIRMS allows
5,000 requests per 10 minutes; each sync uses 4.

## Running

```bash
uv run atlas sync       # one cycle: pull sources → rebuild datasets → index objects into Postgres
uv run atlas worker     # the same cycle every 5 min (--every SECONDS); leave it running
uv run atlas serve      # API + web app on http://127.0.0.1:8000 (API docs at /docs)
```

Run `worker` and `serve` in separate terminals. Other commands:

```bash
uv run atlas index      # rebuild datasets and re-index from what's already landed (no network)
uv run atlas facilities # build OSM facilities now (the worker does this weekly; first full-US run downloads 12 GB)
uv run atlas validate   # check ontology.yaml against the clean datasets
uv run pytest           # parity tests: DuckDB and Postgres backends must answer identically
```

**Settings** (environment variables, or a git-ignored `.env`): `DATABASE_URL` (default
`postgresql://localhost/atlas`), `ATLAS_DATA_DIR` (default `./data`), `ATLAS_OSM_REGIONS` (Geofabrik paths,
default `north-america/us,north-america/us/puerto-rico`), `ATLAS_OSMIUM_BIN` (default `osmium` on PATH),
`NASA_FIRMS_API_KEY`. Set `ATLAS_OBJECT_STORE=duckdb`
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

The map position is kept in the URL (`#zoom/lat/lon`), so any view can be bookmarked or shared,
e.g. `http://localhost:8000/#12/41.83/-71.40` for Providence.

- **Operating picture:** a live map of counties shaded by their worst active alert, with earthquakes sized by
  magnitude and fires by intensity; zoom in to city scale to see facilities (toggle by kind). A side panel shows
  people and hospitals under severe alerts, earthquakes over time, hotspots (counties with both a recent quake
  and an active alert, most people first) and alerts by type. Click anything on the map to open it as an object
  and follow its links.
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
