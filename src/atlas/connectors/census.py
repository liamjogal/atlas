"""Census reference files: county list, county boundaries and population (static, downloaded once)."""

import io
import zipfile

import httpx

from atlas.config import HTTP_HEADERS
from atlas.connectors._landing import landing_dir

GAZETTEER_URL = (
    "https://www2.census.gov/geo/docs/maps-data/data/gazetteer/"
    "2024_Gazetteer/2024_Gaz_counties_national.zip"
)
GAZETTEER_FILE = "2024_Gaz_counties_national.txt"

# Cartographic boundaries (1:500k), read straight from the zip by DuckDB's spatial extension.
BOUNDARIES_URL = "https://www2.census.gov/geo/tiger/GENZ2024/shp/cb_2024_us_county_500k.zip"
BOUNDARIES_FILE = "cb_2024_us_county_500k.zip"

# Annual county population estimates (Vintage 2024).
POPULATION_URL = (
    "https://www2.census.gov/programs-surveys/popest/datasets/"
    "2020-2024/counties/totals/co-est2024-alldata.csv"
)
POPULATION_FILE = "co-est2024-alldata.csv"


def _download(url: str) -> bytes:
    response = httpx.get(url, headers=HTTP_HEADERS, timeout=120, follow_redirects=True)
    response.raise_for_status()
    return response.content


def sync() -> str:
    directory = landing_dir("census_counties")
    fetched = []

    if not (directory / GAZETTEER_FILE).exists():
        with zipfile.ZipFile(io.BytesIO(_download(GAZETTEER_URL))) as archive:
            (directory / GAZETTEER_FILE).write_bytes(archive.read(GAZETTEER_FILE))
        fetched.append("gazetteer")
    if not (directory / BOUNDARIES_FILE).exists():
        (directory / BOUNDARIES_FILE).write_bytes(_download(BOUNDARIES_URL))
        fetched.append("boundaries")
    if not (directory / POPULATION_FILE).exists():
        (directory / POPULATION_FILE).write_bytes(_download(POPULATION_URL))
        fetched.append("population")

    return f"downloaded {', '.join(fetched)}" if fetched else "all reference files present"
