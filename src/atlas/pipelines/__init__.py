"""Pipelines: SQL transforms from landing files to clean datasets.

Transforms run in filename order inside a single transaction, so readers of the
clean tables never see a half-built state.
"""

import re

import duckdb

from atlas.config import LANDING_DIR, TRANSFORMS_DIR

# Landing sources a transform reads as JSON lines: '{landing}/<source>/*.<ndjson|geojsonseq>'.
LANDING_GLOB = re.compile(r"\{landing\}/([\w/]+)/\*\.(ndjson|geojsonseq)")


def ensure_landing_inputs(sql: str) -> None:
    """Give every NDJSON source a transform reads at least one (empty) file.

    DuckDB errors on a glob that matches nothing, which would happen for a source
    that hasn't landed anything yet (no FIRMS key, OSM batches still filling in). An
    empty file reads as zero rows; it is removed as soon as real snapshots exist.
    """
    for source, extension in LANDING_GLOB.findall(sql):
        directory = LANDING_DIR / source
        directory.mkdir(parents=True, exist_ok=True)
        placeholder = directory / f"_empty.{extension}"
        has_data = any(p != placeholder for p in directory.glob(f"*.{extension}"))
        if has_data:
            placeholder.unlink(missing_ok=True)
        else:
            placeholder.touch()


def build(con: duckdb.DuckDBPyConnection) -> dict[str, int]:
    # Point-in-county matching needs the spatial extension (downloaded once, then cached).
    con.execute("INSTALL spatial")
    con.execute("LOAD spatial")
    transforms = [(t, t.read_text()) for t in sorted(TRANSFORMS_DIR.glob("*.sql"))]
    for _, sql in transforms:
        ensure_landing_inputs(sql)

    con.execute("BEGIN")
    try:
        con.execute("CREATE SCHEMA IF NOT EXISTS clean")
        for _, sql in transforms:
            con.execute(sql.replace("{landing}", LANDING_DIR.as_posix()))
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise

    tables = con.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema = 'clean' ORDER BY 1"
    ).fetchall()
    return {
        f"clean.{name}": con.execute(f'SELECT count(*) FROM clean."{name}"').fetchone()[0]
        for (name,) in tables
    }
