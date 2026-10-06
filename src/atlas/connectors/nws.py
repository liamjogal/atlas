"""National Weather Service active alerts (api.weather.gov, no API key).

This is a snapshot sync: every pull replaces the previous one, because an alert
missing from the feed means it has expired or been cancelled.
"""

import httpx

from atlas.config import HTTP_HEADERS
from atlas.connectors._landing import write_snapshot

ALERTS_URL = "https://api.weather.gov/alerts/active"


def sync() -> str:
    response = httpx.get(
        ALERTS_URL,
        params={"status": "actual"},
        headers={**HTTP_HEADERS, "Accept": "application/geo+json"},
        timeout=30,
    )
    response.raise_for_status()

    records = []
    for feature in response.json()["features"]:
        props = feature["properties"]
        records.append({
            "id": props["id"],
            "event": props.get("event"),
            "headline": props.get("headline"),
            "severity": props.get("severity"),
            "urgency": props.get("urgency"),
            "certainty": props.get("certainty"),
            "areaDesc": props.get("areaDesc"),
            "senderName": props.get("senderName"),
            "sent": props.get("sent"),
            "effective": props.get("effective"),
            "expires": props.get("expires"),
            "description": props.get("description"),
            "instruction": props.get("instruction"),
            # SAME codes are "0" + the 5-digit county FIPS; marine zones use other prefixes.
            "same_codes": props.get("geocode", {}).get("SAME", []),
        })

    path = write_snapshot("nws_alerts", records, keep_last=24)
    return f"{len(records)} alerts -> {path.name}"
