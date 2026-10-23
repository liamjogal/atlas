"""One sync cycle: pull every source, rebuild the clean datasets, index them into the object store.

Only this cycle touches DuckDB, and it opens the file just for the length of a cycle,
so the API (which reads Postgres) never contends for it and the file is free between
runs for anyone who wants to inspect it.
"""

import json
import logging
import time
from datetime import datetime, timezone

from atlas.config import DATABASE_URL, LAST_SYNC_PATH, OBJECT_STORE, ONTOLOGY_PATH
from atlas.connectors import CONNECTORS
from atlas.db import connect
from atlas.ontology import load_ontology, ontology_hash
from atlas.pipelines import build

log = logging.getLogger("atlas.sync")


def pull_sources() -> dict[str, str]:
    sources = {}
    for name, connector in CONNECTORS.items():
        try:
            sources[name] = connector()
        except Exception as exc:  # One failing source shouldn't block the others.
            sources[name] = f"FAILED: {exc}"
            log.exception("connector %s failed", name)
    return sources


def run_sync(*, pull: bool = True, schedule_seconds: int | None = None) -> dict:
    """Run one cycle and record it. `pull=False` rebuilds and re-indexes from what's already landed.

    Raises if the pipeline or indexing fails; the failed run is still recorded.
    """
    started_at = datetime.now(timezone.utc)
    ontology = load_ontology(ONTOLOGY_PATH)
    fingerprint = ontology_hash(ONTOLOGY_PATH)
    sources = pull_sources() if pull else {}
    datasets: dict[str, int] = {}
    objects: dict[str, int] = {}
    error: Exception | None = None

    try:
        with connect() as duck:
            datasets = build(duck.cursor())
            problems = ontology.validate_against(duck)
            if problems:
                # A broken pipeline never reaches the object store; the last good index stays live.
                raise RuntimeError("Ontology does not match the datasets:\n  " + "\n  ".join(problems))
            if OBJECT_STORE == "postgres":
                import psycopg

                from atlas.index.indexer import build_index

                with psycopg.connect(DATABASE_URL, autocommit=True) as pg:
                    objects = build_index(ontology, duck, pg)
    except Exception as exc:
        error = exc

    result = {
        "started_at": started_at.isoformat(),
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "status": "failed" if error else "succeeded",
        "error": str(error) if error else None,
        "ontology_hash": fingerprint,
        "schedule_seconds": schedule_seconds,
        "sources": sources,
        "datasets": datasets,
        "objects": objects,
    }
    _record(result)
    if error:
        raise error
    return result


def _record(result: dict) -> None:
    if OBJECT_STORE == "postgres":
        import psycopg

        from atlas.index.indexer import record_sync_run

        with psycopg.connect(DATABASE_URL, autocommit=True) as pg:
            record_sync_run(
                pg,
                **{k: v for k, v in result.items() if k not in ("started_at", "finished_at")},
                started_at=datetime.fromisoformat(result["started_at"]),
                finished_at=datetime.fromisoformat(result["finished_at"]),
            )
    elif result["status"] == "succeeded":
        LAST_SYNC_PATH.write_text(json.dumps(result))


def read_last_sync_file() -> dict | None:
    """The last successful sync in DuckDB-only mode (Postgres mode records to atlas_meta.sync_runs)."""
    return json.loads(LAST_SYNC_PATH.read_text()) if LAST_SYNC_PATH.exists() else None


def run_worker(every_seconds: int) -> None:
    """Sync now, then every `every_seconds`, until interrupted (a minimal scheduler)."""
    log.info("worker started: syncing every %s s", every_seconds)
    while True:
        started = time.monotonic()
        try:
            result = run_sync(schedule_seconds=every_seconds)
            log.info("sync succeeded: %s", result["objects"] or result["datasets"])
        except Exception:
            log.exception("sync failed; the last good index stays live")
        time.sleep(max(0.0, every_seconds - (time.monotonic() - started)))
