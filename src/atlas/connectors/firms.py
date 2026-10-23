"""NASA FIRMS active fire detections (VIIRS satellites, near real time).

Needs a free MAP_KEY from https://firms.modaps.eosdis.nasa.gov/api/map_key/ in the
NASA_FIRMS_API_KEY (or FIRMS_MAP_KEY) environment variable, e.g. in a git-ignored .env
file. Without one, this connector skips and the
pipeline simply produces no fire detections. Append-only like USGS: each sync lands
the last day of detections and the pipeline deduplicates.

Rate limit: FIRMS allows 5,000 transactions per 10 minutes per key. Each sync makes one
request per region below (4), so the default 5-minute worker uses ~8 per 10 minutes.
"""

import csv
import io
import os

import httpx

from atlas.config import HTTP_HEADERS
from atlas.connectors._landing import write_snapshot

SOURCE = "firms_fires"
PRODUCT = "VIIRS_SNPP_NRT"
AREA_URL = "https://firms.modaps.eosdis.nasa.gov/api/area/csv/{key}/{product}/{bbox}/1"

# west,south,east,north. Points outside US counties are dropped later by the pipeline.
REGIONS = {
    "conus": "-125,24,-66,50",
    "alaska": "-170,51,-129,72",
    "hawaii": "-161,18,-154,23",
    "puerto_rico": "-68,17.8,-65,18.6",
}


def parse_csv(text: str) -> list[dict]:
    rows = csv.DictReader(io.StringIO(text))
    return [
        {
            "latitude": float(row["latitude"]),
            "longitude": float(row["longitude"]),
            "acq_date": row["acq_date"],
            "acq_time": row["acq_time"].zfill(4),  # HHMM in UTC
            "satellite": row.get("satellite"),
            "confidence": row.get("confidence"),
            "frp": float(row["frp"]) if row.get("frp") else None,
            "daynight": row.get("daynight"),
        }
        for row in rows
    ]


def sync() -> str:
    key = os.environ.get("NASA_FIRMS_API_KEY") or os.environ.get("FIRMS_MAP_KEY")
    if not key:
        return "skipped: set NASA_FIRMS_API_KEY to enable fire detections"

    records = []
    for bbox in REGIONS.values():
        try:
            response = httpx.get(
                AREA_URL.format(key=key, product=PRODUCT, bbox=bbox), headers=HTTP_HEADERS, timeout=60
            )
        except httpx.HTTPError as exc:
            # httpx errors include the URL, which contains the key; keep only the error type.
            raise RuntimeError(f"FIRMS request failed: {type(exc).__name__}") from None
        if response.status_code != 200:
            # Report the status only: the request URL contains the key.
            raise RuntimeError(f"FIRMS returned HTTP {response.status_code}")
        if not response.text.startswith("latitude"):
            # FIRMS answers bad keys and quota errors with a 200 and a plain-text message.
            raise RuntimeError(f"FIRMS error: {response.text.strip()[:200]}")
        records.extend(parse_csv(response.text))

    if not records:
        return "no detections in the last day"
    # The pipeline keeps 7 days, so ~8 days of 5-minute snapshots is plenty of history.
    path = write_snapshot(SOURCE, records, keep_last=8 * 24 * 12)
    return f"{len(records)} detections -> {path.name}"
