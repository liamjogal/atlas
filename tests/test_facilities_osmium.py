"""End to end: an OSM file -> osmium filter/export -> facilities transform -> clean.facilities.

Uses the real osmium-tool binary, so it runs the same on macOS and in the Linux container.
Skipped where osmium isn't installed.
"""

import shutil
from pathlib import Path

import duckdb
import pytest

from atlas.config import OSMIUM_BIN, TRANSFORMS_DIR
from atlas.connectors import _landing, geofabrik

FIXTURE = Path(__file__).parent / "fixtures" / "tiny_facilities.osm"
REGION = "test/tiny"

pytestmark = pytest.mark.skipif(not shutil.which(OSMIUM_BIN), reason="osmium-tool not installed")


@pytest.fixture
def facilities(tmp_path, monkeypatch):
    osm_dir, landing = tmp_path / "osm", tmp_path / "landing"
    osm_dir.mkdir()
    monkeypatch.setattr(geofabrik, "OSM_DIR", osm_dir)
    monkeypatch.setattr(_landing, "LANDING_DIR", landing)
    # Stand-in for a downloaded Geofabrik extract (osmium reads .osm XML as well as .pbf).
    shutil.copy(FIXTURE, osm_dir / "fixture.osm")
    monkeypatch.setattr(geofabrik, "extract_path", lambda region: osm_dir / "fixture.osm")

    exported = geofabrik.extract_facilities(REGION)

    con = duckdb.connect(":memory:")
    con.execute("INSTALL spatial")
    con.execute("LOAD spatial")
    con.execute("CREATE SCHEMA clean")
    con.execute("""
        CREATE TABLE clean.county_shapes AS
        SELECT * FROM (VALUES
            ('00001', ST_GeomFromText('POLYGON((0 0, 1 0, 1 1, 0 1, 0 0))')),
            ('00002', ST_GeomFromText('POLYGON((1 0, 2 0, 2 1, 1 1, 1 0))'))
        ) AS t(geoid, geom)
    """)
    sql = (TRANSFORMS_DIR / "04_facilities.sql").read_text().replace("{landing}", landing.as_posix())
    con.execute(sql)
    return exported, con


def test_osmium_keeps_only_facilities(facilities):
    exported, _ = facilities
    # hospital node, school+shelter node, and the school way (as a line and as an area); not the cafe
    assert exported == 4


def test_facilities_from_osm_file(facilities):
    _, con = facilities
    rows = con.execute("""
        SELECT facility_id, kind, name, round(latitude, 3), round(longitude, 3), county_geoid,
               address, capacity, emergency
        FROM clean.facilities ORDER BY facility_id
    """).fetchall()
    assert rows == [
        ("hospital/node/1", "hospital", "Center Hospital", 0.5, 0.5, "00001", "1 Main St", 120, True),
        # The building outline becomes its centre point, once (not once per export geometry).
        ("school/node/2", "school", "Gym Shelter School", 0.7, 1.7, "00002", None, None, False),
        ("school/way/20", "school", "Unnamed school", 0.3, 1.3, "00002", None, None, False),
        # The same place is also a shelter: a second facility. "about 50" is not a number.
        ("shelter/node/2", "shelter", "Gym Shelter School", 0.7, 1.7, "00002", None, None, False),
    ]
