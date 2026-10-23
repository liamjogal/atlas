"""Postgres DDL for the object store, generated from the ontology.

Every object type becomes a table and every join-table link becomes a table, in
whichever schema is being built (the indexer builds into a staging schema and
swaps it live). Nothing here names a specific object type.
"""

from atlas.ontology.backends import PostgresBackend, snake_case
from atlas.ontology.registry import LinkTypeDef, ObjectTypeDef, Ontology

# Text columns use the "C" collation (byte order) so sorting matches the pipeline engine
# exactly instead of depending on the server's locale.
COLUMN_TYPES = {**PostgresBackend.sql_types, "string": 'TEXT COLLATE "C"'}

META_DDL = [
    "CREATE EXTENSION IF NOT EXISTS pg_trgm",
    "CREATE SCHEMA IF NOT EXISTS atlas_meta",
    """
    CREATE TABLE IF NOT EXISTS atlas_meta.sync_runs (
        id               BIGSERIAL PRIMARY KEY,
        started_at       TIMESTAMPTZ NOT NULL,
        finished_at      TIMESTAMPTZ NOT NULL,
        status           TEXT NOT NULL,          -- 'succeeded' or 'failed'
        error            TEXT,
        ontology_hash    TEXT NOT NULL,
        schedule_seconds INTEGER,                -- the worker's interval, if it was scheduled
        sources          JSONB NOT NULL,         -- what each connector landed
        datasets         JSONB NOT NULL,         -- row counts of the clean datasets
        objects          JSONB NOT NULL          -- row counts indexed per object type and link
    )
    """,
]


def q(name: str) -> str:
    return f'"{name}"'


def object_table(obj: ObjectTypeDef, schema: str) -> str:
    return f"{schema}.{snake_case(obj.api_name)}"


def join_table(link: LinkTypeDef, schema: str) -> str:
    return f"{schema}.{snake_case(link.api_name)}"


def create_tables(ontology: Ontology, schema: str) -> list[str]:
    statements = [f"CREATE SCHEMA {schema}"]
    for obj in ontology.object_types.values():
        columns = [f"{q(name)} {COLUMN_TYPES[prop.type]}" for name, prop in obj.properties.items()]
        columns.append(f"PRIMARY KEY ({q(obj.primary_key)})")
        statements.append(f"CREATE TABLE {object_table(obj, schema)} ({', '.join(columns)})")

    for link in ontology.link_types:
        if link.cardinality != "many_to_many":
            continue
        source = ontology.object_type(link.source)
        target = ontology.object_type(link.target)
        source_type = COLUMN_TYPES[source.properties[source.primary_key].type]
        target_type = COLUMN_TYPES[target.properties[target.primary_key].type]
        statements.append(
            f"CREATE TABLE {join_table(link, schema)} ("
            f"{q(link.join_source_key)} {source_type} NOT NULL, "
            f"{q(link.join_target_key)} {target_type} NOT NULL, "
            f"PRIMARY KEY ({q(link.join_source_key)}, {q(link.join_target_key)}))"
        )
    return statements


def create_indexes(ontology: Ontology, schema: str) -> list[str]:
    """Indexes for what the API actually does: follow links and search titles.

    Built after the bulk load, which is much faster than maintaining them row by row.
    """
    statements = []
    for obj in ontology.object_types.values():
        if obj.properties[obj.title_property].type == "string":
            # Trigram index: makes `contains` (ILIKE '%text%') searches fast.
            statements.append(
                f"CREATE INDEX ON {object_table(obj, schema)} "
                f"USING gin ({q(obj.title_property)} gin_trgm_ops)"
            )
    for link in ontology.link_types:
        if link.cardinality == "many_to_one":
            # Reverse traversal (County -> its Earthquakes) looks up by the foreign key.
            statements.append(
                f"CREATE INDEX ON {object_table(ontology.object_type(link.source), schema)} ({q(link.foreign_key)})"
            )
        else:
            # The primary key covers source -> target; this covers target -> source.
            statements.append(f"CREATE INDEX ON {join_table(link, schema)} ({q(link.join_target_key)})")
    return statements
