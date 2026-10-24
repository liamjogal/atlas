"""Ontology API: a generic REST interface over every object type and link.

Routes are not written per object type. They are driven by the registry, so
adding an object type to ontology.yaml makes it queryable with no code changes.

The API only reads. It serves the Postgres object store that `atlas worker` keeps
indexed, holds no lock on the pipeline's DuckDB file, and so can run as many
instances as needed.
"""

from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from atlas.config import (
    API_DATABASE_URL, API_STATEMENT_TIMEOUT_MS, OBJECT_STORE, ONTOLOGY_PATH, RATE_LIMIT_PER_MINUTE, WEB_DIST_DIR,
)
from atlas.db import connect
from atlas.ontology import (
    Backend, DuckDBBackend, IndexNotReady, ObjectStore, OntologyQueryError, PostgresBackend, load_ontology,
    ontology_hash,
)
from atlas.sync import read_last_sync_file

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


class WebAppFiles(StaticFiles):
    """Static files where HTML is always revalidated, so a rebuild shows up on the next load.

    Built assets have content hashes in their names, so they can keep normal caching.
    """

    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        if response.headers.get("content-type", "").startswith("text/html"):
            response.headers["Cache-Control"] = "no-cache"
        return response


def apply_steps(object_set, steps: list[Step]):
    for step in steps:
        if step.where:
            object_set = object_set.where(step.where.property, step.where.op, step.where.value)
        if step.search_around:
            object_set = object_set.search_around(step.search_around)
    return object_set


def open_backend(ontology) -> Backend:
    if OBJECT_STORE == "duckdb":
        con = connect(read_only=True)
        problems = ontology.validate_against(con)
        if problems:
            raise RuntimeError("Ontology does not match the data:\n  " + "\n  ".join(problems))
        return DuckDBBackend(con)

    # Starts even before the first index exists: health answers 503 until an ETL run builds it,
    # so a load balancer simply holds traffic during a fresh deployment.
    return PostgresBackend(API_DATABASE_URL, statement_timeout_ms=API_STATEMENT_TIMEOUT_MS)


def last_sync(backend: Backend) -> dict | None:
    if isinstance(backend, PostgresBackend):
        from atlas.index.indexer import latest_sync_run

        with backend.pool.connection() as conn:
            return latest_sync_run(conn)
    return read_last_sync_file()


def create_app() -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        ontology = load_ontology(ONTOLOGY_PATH)
        backend = open_backend(ontology)
        app.state.store = ObjectStore(ontology, backend)
        app.state.ontology_hash = ontology_hash(ONTOLOGY_PATH)
        yield
        backend.close()

    app = FastAPI(title="Atlas Ontology API", lifespan=lifespan)
    if RATE_LIMIT_PER_MINUTE > 0:
        from atlas.ratelimit import RateLimitMiddleware

        app.add_middleware(RateLimitMiddleware, per_minute=RATE_LIMIT_PER_MINUTE)

    def store(request: Request) -> ObjectStore:
        return request.app.state.store

    def run(fn):
        try:
            return fn()
        except KeyError as exc:
            raise HTTPException(404, str(exc.args[0]))
        except OntologyQueryError as exc:
            raise HTTPException(400, str(exc))
        except IndexNotReady as exc:
            raise HTTPException(503, str(exc))

    @app.get("/api/health")
    def health(request: Request):
        backend = store(request).backend
        if isinstance(backend, PostgresBackend) and not backend.is_indexed():
            # Up, but nothing to serve yet: load balancers keep traffic away until an ETL run finishes.
            return JSONResponse(
                {"status": "not_indexed", "object_store": backend.name, "detail": "Run the ETL (atlas sync) to build the index"},
                status_code=503,
            )
        sync = last_sync(backend)
        return {
            "status": "ok",
            "object_store": backend.name,
            "sync_every_seconds": sync.get("schedule_seconds") if sync else None,
            "last_sync": sync,
            # False means ontology.yaml changed since the last index build: run a sync.
            "index_matches_ontology": bool(sync) and sync["ontology_hash"] == request.app.state.ontology_hash,
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

    # Primary keys may contain "/" (e.g. Facility "hospital/way/123"), so they match as paths.
    # The links route is declared first so ".../links/<name>" isn't swallowed by get_object.
    @app.get("/api/objects/{object_type}/{primary_key:path}/links/{link_name}")
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

    @app.get("/api/objects/{object_type}/{primary_key:path}")
    def get_object(request: Request, object_type: str, primary_key: str):
        obj = run(lambda: store(request).get(object_type, primary_key))
        if obj is None:
            raise HTTPException(404, f"{object_type} '{primary_key}' not found")
        return obj

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
        app.mount("/", WebAppFiles(directory=WEB_DIST_DIR, html=True), name="web")

    return app
