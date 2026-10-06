import duckdb

from atlas.config import DATA_DIR, DB_PATH


def connect(read_only: bool = False) -> duckdb.DuckDBPyConnection:
    DATA_DIR.mkdir(exist_ok=True)
    con = duckdb.connect(str(DB_PATH), read_only=read_only)
    # Timestamps come back in the time zone setting; pin it (GLOBAL so cursors inherit it)
    # so output doesn't depend on the host.
    con.execute("SET GLOBAL TimeZone = 'UTC'")
    return con
