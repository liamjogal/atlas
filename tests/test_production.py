"""Production behaviour: the read-only API role, startup before the first index, query timeouts."""

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg import sql

from atlas import api
from atlas.index import indexer
from atlas.ontology import ObjectStore, OntologyQueryError, PostgresBackend

READER = "atlas_test_reader"


def test_reader_role_can_read_every_rebuilt_index_but_never_write(ontology, duck, pg_url, monkeypatch):
    with psycopg.connect(pg_url, autocommit=True) as conn:
        if not conn.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (READER,)).fetchone():
            conn.execute(sql.SQL("CREATE ROLE {}").format(sql.Identifier(READER)))
        monkeypatch.setattr(indexer, "READER_ROLE", READER)

        # Two builds: the second swap replaces the schema the first one granted on.
        indexer.build_index(ontology, duck, conn)
        indexer.build_index(ontology, duck, conn)

        def can(privilege: str, table: str) -> bool:
            return conn.execute("SELECT has_table_privilege(%s, %s, %s)", (READER, table, privilege)).fetchone()[0]

        assert can("SELECT", "ontology.county") and can("SELECT", "ontology.weather_alert_county")
        assert can("SELECT", "atlas_meta.sync_runs")
        assert not can("INSERT", "ontology.county")
        assert not can("DELETE", "ontology.facility")


def test_reader_role_is_created_and_can_log_in(pg_url):
    role, password = "atlas_test_login_reader", "s3cret-for-tests"
    with psycopg.connect(pg_url, autocommit=True) as conn:
        indexer.ensure_reader_role(conn, role, password)
        indexer.ensure_reader_role(conn, role, password)  # idempotent: second run updates, doesn't fail
    host_part = pg_url.split("://", 1)[1].rsplit("/", 1)
    login_url = f"postgresql://{role}:{password}@{host_part[0].split('@')[-1] or 'localhost'}/{host_part[1]}"
    with psycopg.connect(login_url) as reader:
        assert reader.execute("SELECT current_user").fetchone()[0] == role


@pytest.fixture
def empty_db_url(pg_url):
    """A database with no index at all, like a fresh deployment before the first ETL run."""
    admin_url = pg_url.rsplit("/", 1)[0] + "/postgres"
    name = "atlas_test_empty"
    with psycopg.connect(admin_url, autocommit=True) as admin:
        admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        admin.execute(f'CREATE DATABASE "{name}"')
    yield pg_url.rsplit("/", 1)[0] + f"/{name}"
    with psycopg.connect(admin_url, autocommit=True) as admin:
        admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


def test_api_waits_with_503_until_the_first_index(ontology, empty_db_url):
    backend = PostgresBackend(empty_db_url, max_size=2)
    try:
        app = api.create_app()
        app.state.store = ObjectStore(ontology, backend)
        app.state.ontology_hash = "test"
        client = TestClient(app)

        health = client.get("/api/health")
        assert health.status_code == 503 and health.json()["status"] == "not_indexed"
        # The app shell still loads, and object queries say why they can't answer yet.
        assert client.get("/api/ontology").status_code == 200
        assert client.get("/api/objects/County").status_code == 503
    finally:
        backend.close()


def test_slow_queries_are_cancelled(pg_url):
    backend = PostgresBackend(pg_url, max_size=1, statement_timeout_ms=100)
    try:
        with pytest.raises(OntologyQueryError, match="took too long"):
            backend.query("SELECT pg_sleep(1)", ())
    finally:
        backend.close()
