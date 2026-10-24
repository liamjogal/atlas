"""The indexer: loads the pipeline's clean datasets into the Postgres object store.

This is the step between "data" and "objects": it indexes datasets into the
object store that the API serves. It is driven entirely by the ontology:
for each object type it copies exactly the mapped properties from the backing
dataset, and for each join-table link the join dataset.

Each run builds a complete new index in a staging schema, then swaps it live in one
transaction, so readers always see either the old index or the new one, never a mix.
"""

import json
from datetime import datetime

import duckdb
import psycopg
from psycopg import sql

from atlas.config import READER_PASSWORD, READER_ROLE
from atlas.index.schema import META_DDL, create_indexes, create_tables, join_table, object_table, q
from atlas.ontology.registry import Ontology

LIVE, STAGING, OLD = "ontology", "ontology_staging", "ontology_old"


def ensure_meta(conn: psycopg.Connection) -> None:
    with conn.transaction():
        for statement in META_DDL:
            conn.execute(statement)
        if READER_ROLE:
            role = sql.Identifier(READER_ROLE)
            conn.execute(sql.SQL("GRANT USAGE ON SCHEMA atlas_meta TO {}").format(role))
            conn.execute(sql.SQL("GRANT SELECT ON atlas_meta.sync_runs TO {}").format(role))


def ensure_reader_role(conn: psycopg.Connection, role: str | None = None, password: str | None = None) -> None:
    """Create the API's read-only login role, or reset its password to the configured one.

    Runs from the ETL (which can reach the database), so a fresh deployment needs no manual SQL.
    """
    role, password = role or READER_ROLE, password or READER_PASSWORD
    if not (role and password):
        return
    with conn.transaction():
        exists = conn.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role,)).fetchone()
        statement = "ALTER ROLE {} WITH LOGIN PASSWORD {}" if exists else "CREATE ROLE {} LOGIN PASSWORD {}"
        conn.execute(sql.SQL(statement).format(sql.Identifier(role), sql.Literal(password)))
        conn.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
            sql.Identifier(conn.info.dbname), sql.Identifier(role)))


def grant_reader(conn: psycopg.Connection, schema: str, role: str | None = None) -> None:
    """Let the API's read-only role see a freshly built index.

    The index schema is rebuilt from scratch on every run, so grants never carry over:
    they're reissued on the staging schema before it's swapped live.
    """
    role = role or READER_ROLE
    if not role:
        return
    conn.execute(sql.SQL("GRANT USAGE ON SCHEMA {} TO {}").format(sql.Identifier(schema), sql.Identifier(role)))
    conn.execute(sql.SQL("GRANT SELECT ON ALL TABLES IN SCHEMA {} TO {}").format(sql.Identifier(schema), sql.Identifier(role)))


def _copy(conn: psycopg.Connection, duck: duckdb.DuckDBPyConnection, source: str, target: str, columns: list[str]) -> int:
    column_list = ", ".join(q(c) for c in columns)
    rows = duck.execute(f"SELECT {column_list} FROM {source}").fetchall()
    with conn.cursor() as cur, cur.copy(f"COPY {target} ({column_list}) FROM STDIN") as copy:
        for row in rows:
            copy.write_row(row)
    return len(rows)


def build_index(ontology: Ontology, duck: duckdb.DuckDBPyConnection, conn: psycopg.Connection) -> dict[str, int]:
    """Rebuild the object store from the clean datasets and swap it live. Returns row counts."""
    ensure_reader_role(conn)
    ensure_meta(conn)
    counts: dict[str, int] = {}

    with conn.transaction():
        conn.execute(f"DROP SCHEMA IF EXISTS {STAGING} CASCADE")
        for statement in create_tables(ontology, STAGING):
            conn.execute(statement)

        for name, obj in ontology.object_types.items():
            counts[name] = _copy(conn, duck, obj.backing_dataset, object_table(obj, STAGING), list(obj.properties))
        for link in ontology.link_types:
            if link.cardinality == "many_to_many":
                counts[link.api_name] = _copy(
                    conn, duck, link.join_dataset, join_table(link, STAGING),
                    [link.join_source_key, link.join_target_key],
                )

        for statement in create_indexes(ontology, STAGING):
            conn.execute(statement)
        for name, obj in ontology.object_types.items():
            conn.execute(f"ANALYZE {object_table(obj, STAGING)}")
        grant_reader(conn, STAGING)

    # The swap: renames are instant, and doing all three in one transaction makes it atomic.
    with conn.transaction():
        conn.execute(f"DROP SCHEMA IF EXISTS {OLD} CASCADE")
        live_exists = conn.execute(
            "SELECT 1 FROM information_schema.schemata WHERE schema_name = %s", (LIVE,)
        ).fetchone()
        if live_exists:
            conn.execute(f"ALTER SCHEMA {LIVE} RENAME TO {OLD}")
        conn.execute(f"ALTER SCHEMA {STAGING} RENAME TO {LIVE}")
        conn.execute(f"DROP SCHEMA IF EXISTS {OLD} CASCADE")
    return counts


def record_sync_run(
    conn: psycopg.Connection,
    *,
    started_at: datetime,
    finished_at: datetime,
    status: str,
    ontology_hash: str,
    sources: dict,
    datasets: dict,
    objects: dict,
    error: str | None = None,
    schedule_seconds: int | None = None,
) -> None:
    ensure_meta(conn)
    with conn.transaction():
        conn.execute(
            """
            INSERT INTO atlas_meta.sync_runs
                (started_at, finished_at, status, error, ontology_hash, schedule_seconds, sources, datasets, objects)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                started_at, finished_at, status, error, ontology_hash, schedule_seconds,
                json.dumps(sources), json.dumps(datasets), json.dumps(objects),
            ),
        )


def latest_sync_run(conn: psycopg.Connection, status: str | None = "succeeded") -> dict | None:
    """The most recent sync run (by default the most recent successful one), or None."""
    exists = conn.execute("SELECT to_regclass('atlas_meta.sync_runs')").fetchone()[0]
    if not exists:
        return None
    where = "WHERE status = %s" if status else ""
    row = conn.execute(
        f"""
        SELECT started_at, finished_at, status, error, ontology_hash, schedule_seconds, sources, datasets, objects
        FROM atlas_meta.sync_runs {where} ORDER BY id DESC LIMIT 1
        """,
        (status,) if status else (),
    ).fetchone()
    if row is None:
        return None
    keys = ["started_at", "finished_at", "status", "error", "ontology_hash", "schedule_seconds", "sources", "datasets", "objects"]
    return dict(zip(keys, row))
