import json
from datetime import datetime, timezone
from pathlib import Path

from atlas.config import LANDING_DIR


def landing_dir(source: str) -> Path:
    path = LANDING_DIR / source
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_snapshot(source: str, records: list[dict], keep_last: int | None = None) -> Path:
    """Write records as newline-delimited JSON, stamped with the sync time.

    keep_last prunes older snapshots, for sources where only the latest one matters.
    """
    synced_at = datetime.now(timezone.utc)
    directory = landing_dir(source)
    path = directory / f"{synced_at:%Y%m%dT%H%M%SZ}.ndjson"
    with path.open("w") as f:
        for record in records:
            f.write(json.dumps({**record, "_synced_at": synced_at.isoformat()}) + "\n")

    if keep_last is not None:
        for old in sorted(directory.glob("*.ndjson"))[:-keep_last]:
            old.unlink()
    return path


def read_state(source: str) -> dict:
    path = landing_dir(source) / "_state.json"
    return json.loads(path.read_text()) if path.exists() else {}


def write_state(source: str, state: dict) -> None:
    (landing_dir(source) / "_state.json").write_text(json.dumps(state))
