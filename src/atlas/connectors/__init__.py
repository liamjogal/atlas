"""Connectors pull from external sources into the landing zone.

Each sync writes a timestamped snapshot under data/landing/<source>/ and never
modifies earlier ones, so the pipelines can always be replayed from raw history.
OSM facilities are the exception: they refresh weekly on their own schedule (see geofabrik.py),
and the cycle only reports how fresh they are.
"""

from atlas.connectors import census, firms, geofabrik, nws, usgs

# Run in this order on every sync cycle.
CONNECTORS = {
    "census_counties": census.sync,
    "usgs_earthquakes": usgs.sync,
    "nws_alerts": nws.sync,
    "firms_fires": firms.sync,
    "osm_facilities": geofabrik.status,
}
