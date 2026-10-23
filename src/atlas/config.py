import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
LANDING_DIR = DATA_DIR / "landing"
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
