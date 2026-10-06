"""Ontology API: a generic REST interface over every object type and link.

Routes are not written per object type. They are driven by the registry, so
adding an object type to ontology.yaml makes it queryable with no code changes.
(The shape loosely follows Palantir's Ontology API v2.)
"""

from contextlib import asynccontextmanager
from typing import Any

import duckdb
from fastapi import FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from atlas.config import ONTOLOGY_PATH, WEB_DIST_DIR
from atlas.db import connect
from atlas.ontology import ObjectStore, load_ontology
from atlas.ontology.store import OntologyQueryError
from atlas.sync import SyncScheduler, read_last_sync

RESERVED_PARAMS = {"limit", "offset", "order_by", "desc"}


class Filter(BaseModel):
    property: str
    op: str
    value: Any = None


class Step(BaseModel):
    """One step in an object set: either filter the current set or follow a link."""

    where: Filter | None = None
    search_around: str | None = None


class ObjectSetRequest(BaseModel):
    object_type: str
    steps: list[Step] = []
    order_by: str | None = None
    desc: bool = False
    limit: int = 100
    offset: int = 0


class GroupBy(BaseModel):
    property: str
    bucket: str | None = None


class Metric(BaseModel):
    op: str
    property: str


class AggregateRequest(BaseModel):
    object_type: str
    steps: list[Step] = []
    group_by: list[GroupBy] = []
    metrics: list[Metric] = []
    limit: int = 1000


def apply_steps(object_set, steps: list[Step]):
    for step in steps:
        if step.where:
            object_set = object_set.where(step.where.property, step.where.op, step.where.value)
        if step.search_around:
            object_set = object_set.search_around(step.search_around)
    return object_set


def create_app(sync_every: int | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        con = connect()
        ontology = load_ontology(ONTOLOGY_PATH)
        problems = ontology.validate_against(con)
        if problems:
            raise RuntimeError("Ontology does not match the data:\n  " + "\n  ".join(problems))
        app.state.store = ObjectStore(ontology, con)
        app.state.scheduler = None
        if sync_every:
            app.state.scheduler = SyncScheduler(con, sync_every)
            app.state.scheduler.start()
        yield
        if app.state.scheduler:
            app.state.scheduler.stop()
        con.close()

    app = FastAPI(title="Atlas Ontology API", lifespan=lifespan)

    def store(request: Request) -> ObjectStore:
        return request.app.state.store

    def run(fn):
        try:
            return fn()
        except KeyError as exc:
            raise HTTPException(404, str(exc.args[0]))
        except (OntologyQueryError, duckdb.ConversionException, duckdb.InvalidInputException) as exc:
            raise HTTPException(400, str(exc))

    @app.get("/api/health")
    def health(request: Request):
        scheduler = request.app.state.scheduler
        return {
            "status": "ok",
            "sync_every_seconds": scheduler.every_seconds if scheduler else None,
            "last_sync": read_last_sync(),
        }

    @app.get("/api/ontology")
    def describe_ontology(request: Request):
        ontology = store(request).ontology
        return {
            "object_types": {
                name: {
                    **obj.model_dump(exclude={"api_name"}),
                    "links": {
                        side.name: {"target": side.target_type, "many": side.many}
                        for side in ontology.link_sides(name).values()
                    },
                }
                for name, obj in ontology.object_types.items()
            },
            "link_types": [link.model_dump(exclude_none=True) for link in ontology.link_types],
        }

    @app.get("/api/objects/{object_type}")
    def list_objects(
        request: Request,
        object_type: str,
        limit: int = 100,
        offset: int = 0,
        order_by: str | None = None,
        desc: bool = False,
    ):
        """List objects. Filter with `<property>.<op>=<value>`, e.g. `magnitude.gte=4`."""

        def query():
            object_set = store(request).objects(object_type)
            for key, value in request.query_params.multi_items():
                if key in RESERVED_PARAMS:
                    continue
                prop, _, op = key.partition(".")
                object_set = object_set.where(prop, op or "eq", value)
            return {
                "total": object_set.count(),
                "data": object_set.fetch(order_by, desc, limit, offset),
            }

        return run(query)

    @app.get("/api/objects/{object_type}/{primary_key}")
    def get_object(request: Request, object_type: str, primary_key: str):
        obj = run(lambda: store(request).get(object_type, primary_key))
        if obj is None:
            raise HTTPException(404, f"{object_type} '{primary_key}' not found")
        return obj

    @app.get("/api/objects/{object_type}/{primary_key}/links/{link_name}")
    def get_linked(
        request: Request,
        object_type: str,
        primary_key: str,
        link_name: str,
        limit: int = 100,
        order_by: str | None = None,
        desc: bool = False,
    ):
        return run(lambda: {"data": store(request).linked(
            object_type, primary_key, link_name, order_by=order_by, descending=desc, limit=limit,
        )})

    @app.post("/api/objectSets/load")
    def load_object_set(request: Request, body: ObjectSetRequest):
        """Compose filters and link traversals ("search arounds") into one query."""

        def query():
            object_set = apply_steps(store(request).objects(body.object_type), body.steps)
            return {
                "object_type": object_set.object_type,
                "total": object_set.count(),
                "data": object_set.fetch(body.order_by, body.desc, body.limit, body.offset),
            }

        return run(query)

    @app.post("/api/objectSets/aggregate")
    def aggregate_object_set(request: Request, body: AggregateRequest):
        """Group an object set and count it, e.g. earthquakes per day or alerts per event type."""

        def query():
            object_set = apply_steps(store(request).objects(body.object_type), body.steps)
            return {
                "object_type": object_set.object_type,
                "data": object_set.aggregate(
                    [(g.property, g.bucket) for g in body.group_by],
                    [(m.op, m.property) for m in body.metrics],
                    body.limit,
                ),
            }

        return run(query)

    # The built web app (npm run build in web/) is served from the same origin as the API.
    if WEB_DIST_DIR.exists():
        app.mount("/", StaticFiles(directory=WEB_DIST_DIR, html=True), name="web")

    return app
