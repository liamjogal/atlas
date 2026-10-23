"""Shared fixtures: one small, fixed dataset served by both object-store backends.

The data is built in an in-memory DuckDB with the same clean-dataset layout the
pipelines produce, then indexed into a throwaway Postgres database with the real
indexer. The parity tests can then ask both backends the same questions.
"""

import os

import duckdb
import psycopg
import pytest

from atlas.config import ONTOLOGY_PATH
from atlas.index.indexer import build_index
from atlas.ontology import DuckDBBackend, ObjectStore, PostgresBackend, load_ontology

TEST_DATABASE = os.environ.get("ATLAS_TEST_DATABASE", "atlas_test")
ADMIN_URL = os.environ.get("ATLAS_TEST_ADMIN_URL", "postgresql://localhost/postgres")
TEST_URL = ADMIN_URL.rsplit("/", 1)[0] + f"/{TEST_DATABASE}"

FIXTURE_SQL = """
CREATE SCHEMA clean;

CREATE TABLE clean.counties (
    geoid VARCHAR, name VARCHAR, state VARCHAR, land_area_sqmi DOUBLE, latitude DOUBLE, longitude DOUBLE,
    active_alert_count INTEGER, max_alert_severity VARCHAR, max_alert_severity_rank INTEGER,
    recent_quake_count BIGINT, max_quake_magnitude DOUBLE
);
INSERT INTO clean.counties VALUES
    ('06025', 'Imperial County',  'CA', 4177.0, 33.04, -115.35, 2, 'Severe',   3, 3, 2.1),
    ('06037', 'Los Angeles County','CA', 4058.0, 34.32, -118.22, 1, 'Moderate', 2, 1, 1.9),
    ('02016', 'Aleutians West',   'AK', 4390.0, 52.0,  -174.2,  0, NULL,       0, 1, 4.2),
    ('48001', 'anderson County',  'TX', 1062.6, 31.81, -95.65,  1, 'Extreme',  4, 0, NULL);

CREATE TABLE clean.earthquakes (
    event_id VARCHAR, magnitude DOUBLE, place VARCHAR, occurred_at TIMESTAMPTZ, updated_at TIMESTAMPTZ,
    latitude DOUBLE, longitude DOUBLE, depth_km DOUBLE, significance INTEGER, tsunami_flag BOOLEAN,
    pager_alert VARCHAR, review_status VARCHAR, county_geoid VARCHAR, distance_to_county_km DOUBLE, url VARCHAR
);
INSERT INTO clean.earthquakes VALUES
    ('ci1', 2.1, '8 km W of Holtville, CA',  '2026-10-20 10:00:00+00', '2026-10-20 10:05:00+00', 32.8, -115.4, 5.0, 70, false, NULL, 'reviewed', '06025', 4.2, 'https://example.com/ci1'),
    ('ci2', 1.4, '9 km ESE of Ocotillo, CA', '2026-10-21 23:30:00+00', '2026-10-21 23:31:00+00', 32.7, -115.9, 8.1, 30, false, NULL, 'automatic', '06025', 9.0, NULL),
    ('ci3', 1.9, '3 km N of Malibu, CA',     '2026-10-21 01:15:00+00', '2026-10-21 01:20:00+00', 34.0, -118.7, 11.0, 56, false, NULL, 'reviewed', '06037', 20.1, NULL),
    ('ci4', 1.1, '5 km S of Calexico, CA',   '2026-10-22 06:00:00+00', '2026-10-22 06:00:30+00', 32.6, -115.5, 3.3, 19, false, NULL, 'automatic', '06025', 7.7, NULL),
    ('av1', 4.2, '70 km SW of Adak, Alaska', '2026-10-22 12:00:00+00', '2026-10-22 13:00:00+00', 51.5, -177.1, 30.0, 271, true, 'green', 'reviewed', '02016', 61.0, NULL),
    ('us1', 5.9, 'south of the Fiji Islands','2026-10-19 08:00:00+00', '2026-10-19 09:00:00+00', -23.0, 179.0, 500.0, 536, false, NULL, 'reviewed', NULL, NULL, NULL);

CREATE TABLE clean.weather_alerts (
    alert_id VARCHAR, event VARCHAR, headline VARCHAR, severity VARCHAR, urgency VARCHAR, certainty VARCHAR,
    area_description VARCHAR, sender VARCHAR, sent_at TIMESTAMPTZ, effective_at TIMESTAMPTZ, expires_at TIMESTAMPTZ,
    description VARCHAR, instruction VARCHAR
);
INSERT INTO clean.weather_alerts VALUES
    ('a1', 'Extreme Heat Warning', 'Extreme Heat Warning until Oct 24', 'Severe', 'Expected', 'Likely', 'Imperial', 'NWS San Diego',
     '2026-10-22 15:00:00+00', '2026-10-22 15:00:00+00', '2026-10-24 03:00:00+00', 'Hot.', 'Drink water.'),
    ('a2', 'Wind Advisory', 'Wind Advisory for LA and Imperial', 'Moderate', 'Expected', 'Likely', 'LA; Imperial', 'NWS Los Angeles',
     '2026-10-22 18:00:00+00', '2026-10-22 18:00:00+00', '2026-10-23 06:00:00+00', 'Windy.', NULL),
    ('a3', 'Tornado Warning', 'Tornado Warning for Anderson County', 'Extreme', 'Immediate', 'Observed', 'Anderson', 'NWS Fort Worth',
     '2026-10-23 01:00:00+00', '2026-10-23 01:00:00+00', '2026-10-23 01:45:00+00', 'Take cover.', 'Go to a basement.');

CREATE TABLE clean.alert_counties (alert_id VARCHAR, geoid VARCHAR);
INSERT INTO clean.alert_counties VALUES ('a1', '06025'), ('a2', '06037'), ('a2', '06025'), ('a3', '48001');
"""


@pytest.fixture(scope="session")
def ontology():
    return load_ontology(ONTOLOGY_PATH)


@pytest.fixture(scope="session")
def duck():
    con = duckdb.connect(":memory:")
    con.execute("SET GLOBAL TimeZone = 'UTC'")
    con.execute(FIXTURE_SQL)
    yield con
    con.close()


@pytest.fixture(scope="session")
def pg_url(ontology, duck):
    try:
        admin = psycopg.connect(ADMIN_URL, autocommit=True)
    except psycopg.OperationalError:
        pytest.skip("Postgres is not running (brew services start postgresql@17)")
    with admin:
        admin.execute(f'DROP DATABASE IF EXISTS "{TEST_DATABASE}" WITH (FORCE)')
        admin.execute(f'CREATE DATABASE "{TEST_DATABASE}"')
    with psycopg.connect(TEST_URL, autocommit=True) as conn:
        build_index(ontology, duck, conn)
    return TEST_URL


@pytest.fixture(scope="session")
def duck_store(ontology, duck):
    assert ontology.validate_against(duck) == [], "fixture data must match the ontology"
    return ObjectStore(ontology, DuckDBBackend(duck))


@pytest.fixture(scope="session")
def pg_store(ontology, pg_url):
    backend = PostgresBackend(pg_url, max_size=2)
    yield ObjectStore(ontology, backend)
    backend.close()
