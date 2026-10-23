"""Point-in-county matching, by running the real facilities transform on a tiny world."""

import json

import duckdb

from atlas.config import TRANSFORMS_DIR


def feature(osm_type, osm_id, geometry, **tags):
    return {"type": "Feature", "geometry": geometry, "properties": {"@type": osm_type, "@id": osm_id, **tags}}


def point(lon, lat):
    return {"type": "Point", "coordinates": [lon, lat]}


FEATURES = [
    feature("node", 1, point(0.5, 0.5), amenity="hospital"),
    feature("node", 2, point(1.5, 0.5), amenity="school", name="East School"),
    # Outside every county (think: across the border) -> dropped.
    feature("node", 3, point(5.0, 5.0), amenity="school", name="Abroad"),
]


def run_transform(tmp_path, features) -> duckdb.DuckDBPyConnection:
    landing = tmp_path / "osm_facilities"
    landing.mkdir()
    with (landing / "test.geojsonseq").open("w") as f:
        for item in features:
            f.write(json.dumps(item) + "\n")

    con = duckdb.connect(":memory:")
    con.execute("INSTALL spatial")
    con.execute("LOAD spatial")
    con.execute("CREATE SCHEMA clean")
    # Two unit-square "counties" side by side.
    con.execute("""
        CREATE TABLE clean.county_shapes AS
        SELECT * FROM (VALUES
            ('00001', ST_GeomFromText('POLYGON((0 0, 1 0, 1 1, 0 1, 0 0))')),
            ('00002', ST_GeomFromText('POLYGON((1 0, 2 0, 2 1, 1 1, 1 0))'))
        ) AS t(geoid, geom)
    """)
    sql = (TRANSFORMS_DIR / "04_facilities.sql").read_text().replace("{landing}", tmp_path.as_posix())
    con.execute(sql)
    return con


def test_facilities_land_in_the_county_that_contains_them(tmp_path):
    con = run_transform(tmp_path, FEATURES)
    rows = con.execute(
        "SELECT facility_id, county_geoid, name FROM clean.facilities ORDER BY facility_id"
    ).fetchall()
    assert rows == [
        ("hospital/node/1", "00001", "Unnamed hospital"),
        ("school/node/2", "00002", "East School"),
    ]
