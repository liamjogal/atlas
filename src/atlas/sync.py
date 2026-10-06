"""One sync cycle: pull every source into the landing zone, then rebuild clean datasets."""

import logging
import threading
from datetime import datetime, timezone

import duckdb

from atlas.connectors import CONNECTORS
from atlas.pipelines import build

log = logging.getLogger("atlas.sync")


def run_sync(con: duckdb.DuckDBPyConnection) -> dict:
    sources = {}
    for name, connector in CONNECTORS.items():
        try:
            sources[name] = connector()
        except Exception as exc:  # One failing source shouldn't block the others.
            sources[name] = f"FAILED: {exc}"
            log.exception("connector %s failed", name)
    tables = build(con.cursor())
    return {
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "sources": sources,
        "tables": tables,
    }


class SyncScheduler:
    """Runs run_sync on an interval in a background thread (a tiny stand-in for Foundry schedules)."""

    def __init__(self, con: duckdb.DuckDBPyConnection, every_seconds: int):
        self.con = con
        self.every_seconds = every_seconds
        self.last_result: dict | None = None
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.wait(self.every_seconds):
            try:
                self.last_result = run_sync(self.con)
                log.info("sync complete: %s", self.last_result["tables"])
            except Exception:
                log.exception("sync failed")
