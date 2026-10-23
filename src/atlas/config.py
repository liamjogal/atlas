import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _load_dotenv() -> None:
    """Load KEY=value lines from .env files into the environment (secrets such as API keys).

    Looks in the project root and in this package's folder. Variables already set in the
    real environment win. The files are git-ignored; never commit them.
    """
    for path in (PROJECT_ROOT / ".env", Path(__file__).resolve().parent / ".env"):
        if not path.exists():
            continue
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip("'\""))


_load_dotenv()
# Everything Atlas writes lives under one directory: a volume in a container, ./data locally.
DATA_DIR = Path(os.environ.get("ATLAS_DATA_DIR", PROJECT_ROOT / "data")).resolve()
LANDING_DIR = DATA_DIR / "landing"
OSM_DIR = DATA_DIR / "osm"
DB_PATH = DATA_DIR / "atlas.duckdb"
LAST_SYNC_PATH = DATA_DIR / "last_sync.json"
ONTOLOGY_PATH = PROJECT_ROOT / "ontology" / "ontology.yaml"
WEB_DIST_DIR = PROJECT_ROOT / "web" / "dist"
TRANSFORMS_DIR = Path(__file__).resolve().parent / "pipelines" / "transforms"

# api.weather.gov rejects requests without an identifying User-Agent.
HTTP_HEADERS = {"User-Agent": "atlas-ontology-learning-project"}

# Where the API reads objects from: the Postgres object store (default), or the DuckDB
# clean datasets directly ("duckdb", for offline development; no separate worker then).
OBJECT_STORE = os.environ.get("ATLAS_OBJECT_STORE", "postgres")
DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://localhost/atlas")

# Geofabrik extracts to build facilities from (paths under download.geofabrik.de). The full US
# file is ~12 GB; for local development a single small state works, e.g. north-america/us/rhode-island.
OSM_REGIONS = [
    r.strip()
    for r in os.environ.get("ATLAS_OSM_REGIONS", "north-america/us,north-america/us/puerto-rico").split(",")
    if r.strip()
]
# The osmium command-line tool (brew install osmium-tool / apt-get install osmium-tool).
OSMIUM_BIN = os.environ.get("ATLAS_OSMIUM_BIN", "osmium")
