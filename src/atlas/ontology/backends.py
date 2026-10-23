"""Storage backends for the object store.

The ObjectStore builds the same SQL for every engine; a backend supplies only what
differs between engines: where each object type's rows live, the placeholder and
type spellings, and how to run a query. Swapping the backend never changes what an
API caller sees.
"""

from __future__ import annotations

import re
from typing import Protocol

import duckdb

from atlas.ontology.registry import LinkTypeDef, ObjectTypeDef

INDEX_SCHEMA = "ontology"


class OntologyQueryError(ValueError):
    """A query the caller got wrong: unknown property, bad operator, a value that won't cast."""


def snake_case(api_name: str) -> str:
    """WeatherAlert -> weather_alert, weatherAlertCounty -> weather_alert_county."""
    return re.sub(r"(?<!^)(?=[A-Z])", "_", api_name).lower()


class Backend(Protocol):
    name: str
    placeholder: str
    sql_types: dict[str, str]

    def object_table(self, obj: ObjectTypeDef) -> str: ...
    def join_table(self, link: LinkTypeDef) -> str: ...
    def query(self, sql: str, params: tuple) -> list[tuple]: ...
    def close(self) -> None: ...


class DuckDBBackend:
    """Queries the pipeline's clean datasets directly. Used for tests and offline development."""

    name = "duckdb"
    placeholder = "?"
    sql_types = {
        "string": "VARCHAR", "integer": "BIGINT", "double": "DOUBLE",
        "boolean": "BOOLEAN", "timestamp": "TIMESTAMPTZ",
    }

    def __init__(self, con: duckdb.DuckDBPyConnection):
        self.con = con

    def object_table(self, obj: ObjectTypeDef) -> str:
        return obj.backing_dataset

    def join_table(self, link: LinkTypeDef) -> str:
        return link.join_dataset

    def query(self, sql: str, params: tuple) -> list[tuple]:
        try:
            # A cursor per query: DuckDB connections aren't safe to share across request threads.
            return self.con.cursor().execute(sql, params).fetchall()
        except (duckdb.ConversionException, duckdb.InvalidInputException) as exc:
            raise OntologyQueryError(str(exc)) from exc

    def close(self) -> None:
        self.con.close()


class PostgresBackend:
    """Queries the Postgres object store that the indexer builds from the clean datasets."""

    name = "postgres"
    placeholder = "%s"
    sql_types = {
        "string": "TEXT", "integer": "BIGINT", "double": "DOUBLE PRECISION",
        "boolean": "BOOLEAN", "timestamp": "TIMESTAMPTZ",
    }

    def __init__(self, database_url: str, min_size: int = 1, max_size: int = 10):
        from psycopg_pool import ConnectionPool

        self.pool = ConnectionPool(
            database_url,
            min_size=min_size,
            max_size=max_size,
            # Pin the session time zone so timestamps and date_trunc buckets don't depend on the host.
            kwargs={"options": "-c TimeZone=UTC"},
            open=True,
        )

    def object_table(self, obj: ObjectTypeDef) -> str:
        return f"{INDEX_SCHEMA}.{snake_case(obj.api_name)}"

    def join_table(self, link: LinkTypeDef) -> str:
        return f"{INDEX_SCHEMA}.{snake_case(link.api_name)}"

    def query(self, sql: str, params: tuple) -> list[tuple]:
        import psycopg

        try:
            with self.pool.connection() as conn:
                return conn.execute(sql, params).fetchall()
        except psycopg.errors.DataError as exc:
            raise OntologyQueryError(str(exc).splitlines()[0]) from exc

    def close(self) -> None:
        self.pool.close()
