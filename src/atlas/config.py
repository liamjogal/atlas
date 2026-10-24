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
# In production the API connects as a read-only role; locally it can share DATABASE_URL.
API_DATABASE_URL = os.environ.get("ATLAS_READ_ONLY_DATABASE_URL", DATABASE_URL)
# A database role the indexer grants SELECT to on every rebuilt index (the API's read-only role).
READER_ROLE = os.environ.get("ATLAS_READER_ROLE")
# If set, the indexer creates that role (or updates its password) so deployments need no manual SQL.
READER_PASSWORD = os.environ.get("ATLAS_READER_PASSWORD")
# API queries are cancelled after this long, so a public endpoint can't run away with the database.
API_STATEMENT_TIMEOUT_MS = int(os.environ.get("ATLAS_API_STATEMENT_TIMEOUT_MS", "10000"))

# Geofabrik extracts to build facilities from (paths under download.geofabrik.de). The full US
# file is ~12 GB; for local development a single small state works, e.g. north-america/us/rhode-island.
OSM_REGIONS = [
    r.strip()
    for r in os.environ.get("ATLAS_OSM_REGIONS", "north-america/us,north-america/us/puerto-rico").split(",")
    if r.strip()
]
# The osmium command-line tool (brew install osmium-tool / apt-get install osmium-tool).
OSMIUM_BIN = os.environ.get("ATLAS_OSMIUM_BIN", "osmium")
# Max MB of OSM changes pyosmium applies per pass (it holds them in memory). Unset = its default
# (~1 GB); lower it on small machines. Passes repeat until the extract is up to date.
OSM_UPDATE_MAX_MB = os.environ.get("ATLAS_OSM_UPDATE_MAX_MB")

# Per-client API rate limit (requests per minute; 0 = off). In production the client is the
# CloudFront-Viewer-Address header, which CloudFront sets and visitors cannot forge.
RATE_LIMIT_PER_MINUTE = int(os.environ.get("ATLAS_RATE_LIMIT_PER_MINUTE", "0"))
