"""Object store: answers questions about objects, links and object sets.

Callers ask in ontology terms ("Earthquakes with magnitude >= 4, then their
Counties") and the store compiles that into SQL. The SQL is the same for every
engine; a Backend (backends.py) says where each object type's rows live and runs it.
Identifiers in the SQL only ever come from the registry; user input is checked
against it and passed as bound parameters.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from atlas.ontology.backends import Backend, OntologyQueryError
from atlas.ontology.registry import LinkSide, Ontology, ObjectTypeDef

OPERATORS = {
    "eq": "=", "ne": "!=", "gt": ">", "gte": ">=", "lt": "<", "lte": "<=",
    "contains": "ILIKE", "is_null": "IS NULL", "is_not_null": "IS NOT NULL",
}
MAX_PAGE_SIZE = 5000
BUCKETS = {"hour", "day", "week", "month"}
METRICS = {"avg", "min", "max", "sum"}
NUMERIC_TYPES = {"integer", "double"}


def _ident(name: str) -> str:
    return ".".join(f'"{part}"' for part in name.split("."))


@dataclass(frozen=True)
class ObjectSet:
    """An immutable, lazily evaluated set of objects of one type.

    Each step (where, search_around) wraps the previous SQL as a subquery, so sets
    compose freely and nothing touches the database until fetch() or count().
    """

    store: ObjectStore
    object_type: str
    sql: str
    params: tuple = field(default_factory=tuple)

    @property
    def definition(self) -> ObjectTypeDef:
        return self.store.ontology.object_type(self.object_type)

    def where(self, prop: str, op: str, value: Any = None) -> ObjectSet:
        obj = self.definition
        if prop not in obj.properties:
            raise OntologyQueryError(f"{self.object_type} has no property '{prop}'")
        if op not in OPERATORS:
            raise OntologyQueryError(f"Unknown operator '{op}', expected one of {list(OPERATORS)}")

        backend = self.store.backend
        column, sql_op, ph = _ident(prop), OPERATORS[op], backend.placeholder
        if op in ("is_null", "is_not_null"):
            condition, params = f"{column} {sql_op}", ()
        elif op == "contains":
            text = backend.sql_types["string"]
            condition, params = f"CAST({column} AS {text}) ILIKE {ph}", (f"%{value}%",)
        else:
            sql_type = backend.sql_types[obj.properties[prop].type]
            condition, params = f"{column} {sql_op} CAST({ph} AS {sql_type})", (value,)

        return ObjectSet(
            self.store, self.object_type,
            f"SELECT * FROM ({self.sql}) AS s WHERE {condition}",
            self.params + params,
        )

    def search_around(self, link_name: str) -> ObjectSet:
        """Follow a link: the result is every object linked to any object in this set."""
        sides = self.store.ontology.link_sides(self.object_type)
        if link_name not in sides:
            raise OntologyQueryError(
                f"{self.object_type} has no link '{link_name}', expected one of {list(sides)}"
            )
        side: LinkSide = sides[link_name]
        link = side.link
        source = self.definition
        target = self.store.ontology.object_type(side.target_type)
        backend = self.store.backend
        target_table, target_pk = _ident(backend.object_table(target)), _ident(target.primary_key)

        if link.cardinality == "many_to_one" and side.from_source:
            # Earthquake -> County: targets whose key is one of our foreign keys.
            keys = f"SELECT {_ident(link.foreign_key)} FROM ({self.sql}) AS s"
            sql = f"SELECT * FROM {target_table} WHERE {target_pk} IN ({keys})"
        elif link.cardinality == "many_to_one":
            # County -> [Earthquake]: targets whose foreign key points at one of us.
            keys = f"SELECT {_ident(source.primary_key)} FROM ({self.sql}) AS s"
            sql = f"SELECT * FROM {target_table} WHERE {_ident(link.foreign_key)} IN ({keys})"
        else:
            # Many-to-many: hop through the join dataset in whichever direction we're going.
            ours, theirs = (
                (link.join_source_key, link.join_target_key) if side.from_source
                else (link.join_target_key, link.join_source_key)
            )
            keys = f"SELECT {_ident(source.primary_key)} FROM ({self.sql}) AS s"
            joined = (
                f"SELECT {_ident(theirs)} FROM {_ident(backend.join_table(link))} "
                f"WHERE {_ident(ours)} IN ({keys})"
            )
            sql = f"SELECT * FROM {target_table} WHERE {target_pk} IN ({joined})"

        return ObjectSet(self.store, side.target_type, sql, self.params)

    def aggregate(
        self,
        group_by: list[tuple[str, str | None]],
        metrics: list[tuple[str, str]] = (),
        limit: int = 1000,
    ) -> list[dict]:
        """Count (plus optional metrics) per group. Timestamp groups can be bucketed by hour/day/week/month.

        Bucketed groups come back in time order; plain groups come back largest first.
        """
        obj = self.definition
        group_exprs, select_exprs = [], []
        for prop, bucket in group_by:
            if prop not in obj.properties:
                raise OntologyQueryError(f"{self.object_type} has no property '{prop}'")
            expr = _ident(prop)
            if bucket:
                if bucket not in BUCKETS or obj.properties[prop].type != "timestamp":
                    raise OntologyQueryError(f"Bucket '{bucket}' needs a timestamp property and one of {sorted(BUCKETS)}")
                expr = f"date_trunc('{bucket}', {expr})"
            group_exprs.append(expr)
            select_exprs.append(f"{expr} AS {_ident(prop)}")

        metric_names = []
        for op, prop in metrics:
            if op not in METRICS:
                raise OntologyQueryError(f"Unknown metric '{op}', expected one of {sorted(METRICS)}")
            if obj.properties.get(prop) is None or obj.properties[prop].type not in NUMERIC_TYPES:
                raise OntologyQueryError(f"Metric '{op}' needs a numeric property, got '{prop}'")
            metric_names.append(f"{op}_{prop}")
            select_exprs.append(f"{op}({_ident(prop)}) AS {_ident(metric_names[-1])}")

        bucketed = any(bucket for _, bucket in group_by)
        # Ties are broken by the group values so results are deterministic on every engine.
        order = ", ".join(group_exprs) if bucketed else ", ".join(["count DESC", *group_exprs])
        sql = (
            f"SELECT {', '.join(select_exprs + ['count(*) AS count'])} FROM ({self.sql}) AS s "
            + (f"GROUP BY {', '.join(group_exprs)} " if group_exprs else "")
            + f"ORDER BY {order} LIMIT {max(1, min(limit, MAX_PAGE_SIZE))}"
        )
        rows = self.store.backend.query(sql, self.params)
        group_names = [prop for prop, _ in group_by]
        return [
            {
                "group": dict(zip(group_names, row[: len(group_names)])),
                "metrics": dict(zip(metric_names, row[len(group_names) : -1])),
                "count": row[-1],
            }
            for row in rows
        ]

    def count(self) -> int:
        return self.store.backend.query(f"SELECT count(*) FROM ({self.sql}) AS s", self.params)[0][0]

    def fetch(
        self,
        order_by: str | None = None,
        descending: bool = False,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict]:
        obj = self.definition
        order_by = order_by or obj.primary_key
        if order_by not in obj.properties:
            raise OntologyQueryError(f"{self.object_type} has no property '{order_by}'")
        limit = max(1, min(limit, MAX_PAGE_SIZE))

        columns = ", ".join(_ident(p) for p in obj.properties)
        direction = "DESC" if descending else "ASC"
        sql = (
            f"SELECT {columns} FROM ({self.sql}) AS s "
            f"ORDER BY {_ident(order_by)} {direction} NULLS LAST, {_ident(obj.primary_key)} "
            f"LIMIT {limit} OFFSET {int(offset)}"
        )
        rows = self.store.backend.query(sql, self.params)
        return [self.store.to_object(obj, dict(zip(obj.properties, row))) for row in rows]


class ObjectStore:
    def __init__(self, ontology: Ontology, backend: Backend):
        self.ontology = ontology
        self.backend = backend

    def objects(self, object_type: str) -> ObjectSet:
        obj = self.ontology.object_type(object_type)
        return ObjectSet(self, object_type, f"SELECT * FROM {_ident(self.backend.object_table(obj))}")

    def get(self, object_type: str, primary_key: Any) -> dict | None:
        obj = self.ontology.object_type(object_type)
        results = self.objects(object_type).where(obj.primary_key, "eq", primary_key).fetch(limit=1)
        return results[0] if results else None

    def linked(self, object_type: str, primary_key: Any, link_name: str, **fetch_args) -> list[dict]:
        obj = self.ontology.object_type(object_type)
        return (
            self.objects(object_type)
            .where(obj.primary_key, "eq", primary_key)
            .search_around(link_name)
            .fetch(**fetch_args)
        )

    @staticmethod
    def to_object(obj: ObjectTypeDef, properties: dict) -> dict:
        return {
            "__apiName": obj.api_name,
            "__primaryKey": properties[obj.primary_key],
            "__title": properties[obj.title_property],
            **properties,
        }
