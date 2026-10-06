"""Pipelines: SQL transforms from landing files to clean datasets.

Transforms run in filename order inside a single transaction, so readers of the
clean tables never see a half-built state.
"""

import duckdb

from atlas.config import LANDING_DIR, TRANSFORMS_DIR


def build(con: duckdb.DuckDBPyConnection) -> dict[str, int]:
    con.execute("BEGIN")
    try:
        con.execute("CREATE SCHEMA IF NOT EXISTS clean")
        for transform in sorted(TRANSFORMS_DIR.glob("*.sql")):
            sql = transform.read_text().replace("{landing}", LANDING_DIR.as_posix())
            con.execute(sql)
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
