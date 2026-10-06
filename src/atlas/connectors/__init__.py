"""Connectors pull from external sources into the landing zone.

Each sync writes a timestamped snapshot under data/landing/<source>/ and never
modifies earlier ones, so the pipelines can always be replayed from raw history.
"""

from atlas.connectors import census, nws, usgs

CONNECTORS = {
    "census_counties": census.sync,
    "usgs_earthquakes": usgs.sync,
    "nws_alerts": nws.sync,
}
