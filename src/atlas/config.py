from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
LANDING_DIR = DATA_DIR / "landing"
DB_PATH = DATA_DIR / "atlas.duckdb"
ONTOLOGY_PATH = PROJECT_ROOT / "ontology" / "ontology.yaml"
TRANSFORMS_DIR = Path(__file__).resolve().parent / "pipelines" / "transforms"

# api.weather.gov rejects requests without an identifying User-Agent.
HTTP_HEADERS = {"User-Agent": "atlas-ontology-learning-project"}
