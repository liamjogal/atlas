"""USGS real-time earthquake feed (GeoJSON, refreshed every minute, no API key).

This is an incremental (append) sync: we keep a high-watermark of the latest
`updated` time seen and only land events that are new or revised since then,
so history accumulates without re-landing the same week of data every run.
"""

import time

import httpx

from atlas.config import HTTP_HEADERS
from atlas.connectors._landing import read_state, write_snapshot, write_state

SOURCE = "usgs_earthquakes"
FEED_URL = "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/{window}.geojson"
DAY_MS = 24 * 60 * 60 * 1000


def sync() -> str:
    watermark = read_state(SOURCE).get("max_updated_ms", 0)
    # Backfill a week on the first run (or after a long gap), otherwise the daily feed is enough.
    window = "all_day" if time.time() * 1000 - watermark < DAY_MS else "all_week"

    response = httpx.get(FEED_URL.format(window=window), headers=HTTP_HEADERS, timeout=30)
    response.raise_for_status()

    records = []
    for feature in response.json()["features"]:
        props = feature["properties"]
        if props["updated"] <= watermark:
            continue
        lon, lat, depth = feature["geometry"]["coordinates"]
        records.append({
            "id": feature["id"],
            **props,
            "longitude": lon,
            "latitude": lat,
            "depth": depth,
        })

    if not records:
        return f"no new or revised events ({window})"

    path = write_snapshot(SOURCE, records)
    write_state(SOURCE, {"max_updated_ms": max(r["updated"] for r in records)})
    return f"{len(records)} new/revised events ({window}) -> {path.name}"
