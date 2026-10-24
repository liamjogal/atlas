"""OpenStreetMap facilities (hospitals, shelters, fire stations, schools) from Geofabrik extracts.

Instead of querying a shared server, Atlas keeps its own copy of the OpenStreetMap data:

  1. download each Geofabrik extract once (the full US is ~12 GB), verified against its MD5;
  2. on later refreshes, apply Geofabrik's daily change files in place (pyosmium-up-to-date);
  3. filter it down to facility tags and export them as GeoJSON lines (osmium-tool),
     which land in data/landing/osm_facilities/ for the pipeline.

Facilities change over months, so this runs weekly on its own schedule outside the
5-minute sync (`atlas worker` runs it in a background thread; `atlas facilities` by hand).
It needs the `osmium` command-line tool on PATH (brew/apt package osmium-tool).

Data © OpenStreetMap contributors (ODbL), extracts by Geofabrik GmbH.
"""

import hashlib
import logging
import shutil
import subprocess
import sys
import time
from pathlib import Path

import httpx

from atlas.config import HTTP_HEADERS, OSM_DIR, OSM_REGIONS, OSM_UPDATE_MAX_MB, OSMIUM_BIN
from atlas.connectors._landing import landing_dir, read_state, write_state

log = logging.getLogger("atlas.geofabrik")

SOURCE = "osm_facilities"
BASE_URL = "https://download.geofabrik.de"

# osmium tags-filter expressions: any node, way or relation (nwr) with one of these tags.
FACILITY_FILTERS = ["nwr/amenity=hospital,school,fire_station", "nwr/social_facility=shelter"]

REFRESH_SECONDS = 7 * 24 * 60 * 60
CHUNK = 8 * 1024 * 1024


class SetupError(RuntimeError):
    """Something missing on this machine (e.g. osmium-tool), not a data problem."""


def _osmium() -> str:
    path = shutil.which(OSMIUM_BIN)
    if not path:
        raise SetupError(
            f"'{OSMIUM_BIN}' not found: install osmium-tool (brew install osmium-tool / "
            "apt-get install osmium-tool) or set ATLAS_OSMIUM_BIN"
        )
    return path


def _up_to_date_tool() -> str:
    # Installed as a console script next to this Python (the project's virtualenv).
    local = Path(sys.executable).parent / "pyosmium-up-to-date"
    return str(local) if local.exists() else shutil.which("pyosmium-up-to-date") or "pyosmium-up-to-date"


def _slug(region: str) -> str:
    return region.replace("/", "_")


def extract_path(region: str) -> Path:
    return OSM_DIR / f"{_slug(region)}.osm.pbf"


def _run(args: list[str]) -> subprocess.CompletedProcess:
    log.info("running %s %s", Path(args[0]).name, " ".join(args[1:3]))
    return subprocess.run(args, capture_output=True, text=True)


def download_extract(region: str) -> Path:
    """Download a region's extract, resuming a partial download, and verify it against Geofabrik's MD5."""
    OSM_DIR.mkdir(parents=True, exist_ok=True)
    target = extract_path(region)
    partial = target.with_suffix(".pbf.part")
    url = f"{BASE_URL}/{region}-latest.osm.pbf"

    expected_md5 = httpx.get(f"{url}.md5", headers=HTTP_HEADERS, timeout=60, follow_redirects=True)
    expected_md5.raise_for_status()
    expected = expected_md5.text.split()[0]

    failures = 0
    while True:
        done = partial.stat().st_size if partial.exists() else 0
        headers = {**HTTP_HEADERS, **({"Range": f"bytes={done}-"} if done else {})}
        try:
            with httpx.stream("GET", url, headers=headers, timeout=httpx.Timeout(60, read=300),
                              follow_redirects=True) as response:
                if response.status_code == 416:  # nothing left to fetch
                    break
                response.raise_for_status()
                mode = "ab" if response.status_code == 206 else "wb"  # 200 = server restarted from zero
                with partial.open(mode) as f:
                    for chunk in response.iter_bytes(CHUNK):
                        f.write(chunk)
        except httpx.TransportError as exc:
            # A dropped connection on a multi-GB download: resume from where it stopped.
            failures += 1
            if failures > 5:
                raise RuntimeError(f"{region}: download kept failing ({exc}); will resume next refresh") from exc
            log.warning("%s download interrupted (%s), resuming", region, exc)
            time.sleep(10 * failures)
            continue
        total = response.headers.get("content-range", "").rsplit("/", 1)[-1]
        if not total.isdigit() or partial.stat().st_size >= int(total):
            break

    digest = hashlib.md5()
    with partial.open("rb") as f:
        while chunk := f.read(CHUNK):
            digest.update(chunk)
    if digest.hexdigest() != expected:
        partial.unlink()
        raise RuntimeError(f"{region}: checksum mismatch, download discarded (will retry)")
    partial.replace(target)
    return target


def update_extract(region: str) -> str:
    """Apply Geofabrik's daily change files to the local extract, in place."""
    # Must match the replication URL in the file's header exactly (no trailing slash).
    server = f"{BASE_URL}/{region}-updates"
    path = extract_path(region)
    for _ in range(40):  # each pass applies up to --size of changes; 1 can mean "more available"
        before = path.stat().st_mtime_ns
        size = ["--size", str(OSM_UPDATE_MAX_MB)] if OSM_UPDATE_MAX_MB else []
        result = _run([_up_to_date_tool(), "--server", server, *size, str(path)])
        if result.returncode == 0:
            return "up to date"
        # Exit code 1 means "partly applied, run again", but argument errors also exit 1 and
        # leave the file untouched; only count it as progress if the file actually changed.
        if result.returncode != 1 or path.stat().st_mtime_ns == before:
            raise RuntimeError(f"{region}: update failed: {result.stderr.strip()[-300:]}")
    return "partially updated (more changes next refresh)"


def extract_facilities(region: str) -> int:
    """Filter the extract to facility tags and export them as GeoJSON lines into the landing zone."""
    osmium = _osmium()
    work = OSM_DIR / f"{_slug(region)}.facilities.osm.pbf"
    landing = landing_dir(SOURCE)
    tmp = landing / f".{_slug(region)}.geojsonseq.tmp"

    steps = [
        [osmium, "tags-filter", str(extract_path(region)), *FACILITY_FILTERS, "-o", str(work), "--overwrite"],
        # -a type,id keeps the OSM identity; no record separators = plain JSON lines.
        [osmium, "export", str(work), "-f", "geojsonseq", "--format-option", "print_record_separator=false",
         "-a", "type,id", "-o", str(tmp), "--overwrite"],
    ]
    for step in steps:
        result = _run(step)
        if result.returncode != 0:
            raise RuntimeError(f"{region}: osmium {step[1]} failed: {result.stderr.strip()[-300:]}")

    tmp.replace(landing / f"{_slug(region)}.geojsonseq")  # atomic: the pipeline never reads half a file
    with (landing / f"{_slug(region)}.geojsonseq").open() as f:
        return sum(1 for _ in f)


def refresh_region(region: str) -> str:
    started = time.monotonic()
    if extract_path(region).exists():
        action = update_extract(region)
    else:
        download_extract(region)
        action = "downloaded"
    features = extract_facilities(region)
    return f"{action}, {features} facility features in {time.monotonic() - started:.0f}s"


def refresh_due(force: bool = False) -> dict[str, str]:
    """Refresh every configured region not refreshed within REFRESH_SECONDS (or all, with force)."""
    try:
        _osmium()
    except SetupError as exc:
        return {"setup": f"skipped: {exc}"}

    refreshed_at = read_state(SOURCE)
    results = {}
    for region in OSM_REGIONS:
        if not force and time.time() - refreshed_at.get(region, 0) < REFRESH_SECONDS:
            continue
        try:
            results[region] = refresh_region(region)
            refreshed_at[region] = time.time()
            write_state(SOURCE, refreshed_at)
        except Exception as exc:
            results[region] = f"FAILED: {exc}"
            log.exception("refreshing %s failed", region)
    return results


def status() -> str:
    """Reported on every sync cycle: how fresh each region is (refreshing happens elsewhere)."""
    if not shutil.which(OSMIUM_BIN):
        return "skipped: install osmium-tool to build facilities"
    refreshed_at = read_state(SOURCE)
    now = time.time()
    return ", ".join(
        f"{region.rsplit('/', 1)[-1]} {(now - refreshed_at[region]) / 3600:.0f}h ago"
        if region in refreshed_at else f"{region.rsplit('/', 1)[-1]} pending"
        for region in OSM_REGIONS
    )


def run_refresher(stop) -> None:
    """Background loop for the worker: check hourly, refresh whatever is due."""
    while not stop.is_set():
        results = refresh_due()
        if results:
            log.info("facility refresh: %s", results)
        stop.wait(60 * 60)
