"""Ontology registry: loads ontology.yaml into typed definitions and checks them.

Validation runs in two stages:
  1. Internal consistency (links point at real object types, keys are real properties).
  2. Against the data (every backing dataset and column exists with a compatible type).
"""

import hashlib
from pathlib import Path
from typing import Literal

import duckdb
import yaml
from pydantic import BaseModel, model_validator

PropertyType = Literal["string", "integer", "double", "boolean", "timestamp"]

# Which DuckDB column types may back each ontology property type.
COMPATIBLE_COLUMN_TYPES: dict[str, set[str]] = {
    "string": {"VARCHAR"},
    "integer": {"INTEGER", "BIGINT", "SMALLINT", "TINYINT", "HUGEINT"},
    "double": {"DOUBLE", "FLOAT", "DECIMAL"},
    "boolean": {"BOOLEAN"},
    "timestamp": {"TIMESTAMP", "TIMESTAMP WITH TIME ZONE"},
}


class PropertyDef(BaseModel):
    type: PropertyType
    description: str | None = None


class ObjectTypeDef(BaseModel):
    api_name: str = ""
    description: str | None = None
    backing_dataset: str
    primary_key: str
    title_property: str
    properties: dict[str, PropertyDef]

    @model_validator(mode="after")
    def keys_are_properties(self):
        for field in ("primary_key", "title_property"):
            if getattr(self, field) not in self.properties:
                raise ValueError(f"{field} '{getattr(self, field)}' is not a property")
        return self


class LinkTypeDef(BaseModel):
    api_name: str
    source: str
    target: str
    source_side_name: str
    target_side_name: str
    cardinality: Literal["many_to_one", "many_to_many"]
    foreign_key: str | None = None
    join_dataset: str | None = None
    join_source_key: str | None = None
    join_target_key: str | None = None

    @model_validator(mode="after")
    def backing_matches_cardinality(self):
        if self.cardinality == "many_to_one" and not self.foreign_key:
            raise ValueError(f"{self.api_name}: many_to_one links need a foreign_key")
        if self.cardinality == "many_to_many" and not (
            self.join_dataset and self.join_source_key and self.join_target_key
        ):
            raise ValueError(f"{self.api_name}: many_to_many links need a join_dataset and keys")
        return self


class LinkSide(BaseModel):
    """A link as seen from one object type: where it leads and whether it returns many."""

    name: str
    link: LinkTypeDef
    from_source: bool
    target_type: str
    many: bool


class Ontology(BaseModel):
    object_types: dict[str, ObjectTypeDef]
    link_types: list[LinkTypeDef] = []

    @model_validator(mode="after")
    def check_links(self):
        for name, obj in self.object_types.items():
            obj.api_name = name
        for link in self.link_types:
            for end in (link.source, link.target):
                if end not in self.object_types:
                    raise ValueError(f"{link.api_name}: unknown object type '{end}'")
            if link.foreign_key and link.foreign_key not in self.object_types[link.source].properties:
                raise ValueError(f"{link.api_name}: foreign_key '{link.foreign_key}' is not a property")
        return self

    def object_type(self, name: str) -> ObjectTypeDef:
        if name not in self.object_types:
            raise KeyError(f"Unknown object type '{name}'")
        return self.object_types[name]

    def link_sides(self, object_type: str) -> dict[str, LinkSide]:
        """Every link traversable from this object type, keyed by its side name."""
        sides = {}
        for link in self.link_types:
            if link.source == object_type:
                sides[link.source_side_name] = LinkSide(
                    name=link.source_side_name, link=link, from_source=True,
                    target_type=link.target, many=link.cardinality == "many_to_many",
                )
            if link.target == object_type:
                sides[link.target_side_name] = LinkSide(
                    name=link.target_side_name, link=link, from_source=False,
                    target_type=link.source, many=True,
                )
        return sides

    def validate_against(self, con: duckdb.DuckDBPyConnection) -> list[str]:
        """Return a list of problems where the ontology and the data disagree."""
        columns: dict[str, dict[str, str]] = {}
        for schema, table, column, dtype in con.execute(
            "SELECT table_schema, table_name, column_name, data_type FROM information_schema.columns"
        ).fetchall():
            columns.setdefault(f"{schema}.{table}", {})[column] = dtype

        problems = []
        for obj in self.object_types.values():
            table = columns.get(obj.backing_dataset)
            if table is None:
                problems.append(f"{obj.api_name}: backing dataset {obj.backing_dataset} not found")
                continue
            for prop_name, prop in obj.properties.items():
                dtype = table.get(prop_name)
                if dtype is None:
                    problems.append(f"{obj.api_name}.{prop_name}: no column in {obj.backing_dataset}")
                elif dtype.split("(")[0] not in COMPATIBLE_COLUMN_TYPES[prop.type]:
                    problems.append(f"{obj.api_name}.{prop_name}: column is {dtype}, expected {prop.type}")

        for link in self.link_types:
            if link.join_dataset:
                table = columns.get(link.join_dataset, {})
                for key in (link.join_source_key, link.join_target_key):
                    if key not in table:
                        problems.append(f"{link.api_name}: {link.join_dataset}.{key} not found")
        return problems


def load_ontology(path: Path) -> Ontology:
    return Ontology.model_validate(yaml.safe_load(path.read_text()))


def ontology_hash(path: Path) -> str:
    """A short fingerprint of the ontology definition, recorded with every index build.

    If the API's ontology and the index's fingerprint differ, the index is out of date.
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()[:12]
