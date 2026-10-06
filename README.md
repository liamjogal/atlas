# Atlas

A mini Palantir-style ontology platform applied to disaster response. It pulls live
earthquake (USGS) and weather-alert (NWS) feeds into a typed ontology of linked objects
and serves them through a generic, schema-driven API.

## Quick start

```bash
uv run atlas sync       # pull all sources and rebuild clean datasets
uv run atlas validate   # check ontology.yaml against the data
uv run atlas serve      # API on http://127.0.0.1:8000 (docs at /docs), re-syncs every 5 min
```

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

| Layer | Where | Palantir equivalent |
| --- | --- | --- |
| Connectors + landing zone | `src/atlas/connectors/`, `data/landing/` | Data Connection, raw datasets |
| Pipelines | `src/atlas/pipelines/transforms/*.sql` | Pipeline Builder, Transforms |
| Ontology | `ontology/ontology.yaml`, `src/atlas/ontology/registry.py` | Ontology Manager |
| Object store + object sets | `src/atlas/ontology/store.py` | Object Set Service |
| Ontology API (objects, links, object sets, aggregations) | `src/atlas/api.py` | Ontology API v2, OSDK |
| Web app | `web/` | Workshop, Object Explorer |

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

DuckDB allows one writer process, so stop `atlas serve` before running `atlas sync` separately.
