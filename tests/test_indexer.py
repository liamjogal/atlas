import psycopg

from atlas.index.indexer import build_index, latest_sync_run, record_sync_run


def schemas(conn) -> set[str]:
    return {row[0] for row in conn.execute("SELECT schema_name FROM information_schema.schemata")}


def test_reindex_swaps_cleanly(ontology, duck, pg_url):
    with psycopg.connect(pg_url, autocommit=True) as conn:
        first = build_index(ontology, duck, conn)
        second = build_index(ontology, duck, conn)

        assert first == second == {
            "County": 4, "Earthquake": 6, "WeatherAlert": 3, "Facility": 4, "FireDetection": 2,
            "weatherAlertCounty": 4,
        }
        # Only the live index remains: no staging or old schema left behind.
        assert "ontology" in schemas(conn)
        assert not {"ontology_staging", "ontology_old"} & schemas(conn)
        assert conn.execute("SELECT count(*) FROM ontology.earthquake").fetchone()[0] == 6


def test_failed_build_keeps_last_good_index(ontology, duck, pg_url):
    broken = duck.cursor()
    broken.execute("CREATE TABLE clean.earthquakes_backup AS SELECT * FROM clean.earthquakes")
    # A duplicate primary key makes the load fail partway through.
    broken.execute("INSERT INTO clean.earthquakes SELECT * FROM clean.earthquakes LIMIT 1")
    try:
        with psycopg.connect(pg_url, autocommit=True) as conn:
            try:
                build_index(ontology, broken, conn)
                raise AssertionError("expected the duplicate key to fail the build")
            except psycopg.errors.UniqueViolation:
                pass
            assert conn.execute("SELECT count(*) FROM ontology.earthquake").fetchone()[0] == 6
            assert "ontology_staging" not in schemas(conn)
    finally:
        broken.execute("DELETE FROM clean.earthquakes")
        broken.execute("INSERT INTO clean.earthquakes SELECT * FROM clean.earthquakes_backup")
        broken.execute("DROP TABLE clean.earthquakes_backup")


def test_sync_runs_record_latest_success(pg_url):
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    with psycopg.connect(pg_url, autocommit=True) as conn:
        for status in ("succeeded", "failed"):
            record_sync_run(
                conn, started_at=now, finished_at=now, status=status, ontology_hash="abc",
                sources={}, datasets={}, objects={"County": 4}, error="boom" if status == "failed" else None,
            )
        assert latest_sync_run(conn)["status"] == "succeeded"
        assert latest_sync_run(conn, status=None)["error"] == "boom"
