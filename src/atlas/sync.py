"""One sync cycle: pull every source into the landing zone, then rebuild clean datasets."""

import json
import logging
import threading
from datetime import datetime, timezone

import duckdb

from atlas.config import LAST_SYNC_PATH
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
    result = {
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "sources": sources,
        "tables": tables,
    }
    LAST_SYNC_PATH.write_text(json.dumps(result))
    return result


def read_last_sync() -> dict | None:
    return json.loads(LAST_SYNC_PATH.read_text()) if LAST_SYNC_PATH.exists() else None


class SyncScheduler:
    """Runs run_sync on an interval in a background thread (a tiny stand-in for Foundry schedules)."""

    def __init__(self, con: duckdb.DuckDBPyConnection, every_seconds: int):
        self.con = con
        self.every_seconds = every_seconds
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _seconds_until_due(self) -> float:
        last = read_last_sync()
        if last is None:
            return 0
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(last["finished_at"])).total_seconds()
        return max(0, self.every_seconds - age)

    def _loop(self) -> None:
        # Due times come from the last recorded sync, so a restart catches up right away
        # instead of serving stale data for a full interval.
        while not self._stop.wait(self._seconds_until_due()):
            try:
                result = run_sync(self.con)
                log.info("sync complete: %s", result["tables"])
            except Exception:
                log.exception("sync failed")
                # A failed sync leaves the last record unchanged, so back off before retrying.
                if self._stop.wait(min(60, self.every_seconds)):
                    return
