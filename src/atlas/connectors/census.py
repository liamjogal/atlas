"""Census Gazetteer county reference file (static, downloaded once)."""

import io
import zipfile

import httpx

from atlas.config import HTTP_HEADERS
from atlas.connectors._landing import landing_dir

GAZETTEER_URL = (
    "https://www2.census.gov/geo/docs/maps-data/data/gazetteer/"
    "2024_Gazetteer/2024_Gaz_counties_national.zip"
)
FILENAME = "2024_Gaz_counties_national.txt"


def sync() -> str:
    path = landing_dir("census_counties") / FILENAME
    if path.exists():
        return f"already present -> {path.name}"

    response = httpx.get(GAZETTEER_URL, headers=HTTP_HEADERS, timeout=60)
    response.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        path.write_bytes(archive.read(FILENAME))
    return f"downloaded -> {path.name}"
