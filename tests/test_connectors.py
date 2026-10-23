"""Connector parsing, from saved sample payloads (no network). OSM facilities: test_facilities_osmium.py."""

from atlas.connectors import firms

FIRMS_SAMPLE = """latitude,longitude,bright_ti4,scan,track,acq_date,acq_time,satellite,instrument,confidence,version,bright_ti5,frp,daynight
34.12345,-117.5432,330.5,0.39,0.36,2026-10-23,812,N,VIIRS,n,2.0NRT,290.1,12.4,N
36.5,-119.25,341.2,0.41,0.37,2026-10-23,2105,N,VIIRS,h,2.0NRT,295.3,,D
"""


def test_firms_csv_becomes_detections():
    first, second = firms.parse_csv(FIRMS_SAMPLE)
    assert first == {
        "latitude": 34.12345, "longitude": -117.5432, "acq_date": "2026-10-23", "acq_time": "0812",
        "satellite": "N", "confidence": "n", "frp": 12.4, "daynight": "N",
    }
    assert second["acq_time"] == "2105"
    assert second["frp"] is None


def test_firms_skips_without_a_key(monkeypatch):
    monkeypatch.delenv("NASA_FIRMS_API_KEY", raising=False)
    monkeypatch.delenv("FIRMS_MAP_KEY", raising=False)
    assert firms.sync().startswith("skipped")
