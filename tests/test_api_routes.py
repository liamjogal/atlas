"""API routing: primary keys containing "/" (OSM-based Facility ids) must work for get and links."""

import pytest
from fastapi.testclient import TestClient

from atlas import api
from atlas.ontology import ObjectStore


@pytest.fixture
def client(ontology, duck_store):
    # Serve the parity fixture data through the real app, without Postgres or a lifespan.
    app = api.create_app()
    app.state.store = ObjectStore(ontology, duck_store.backend)
    app.state.ontology_hash = "test"
    # Not used as a context manager, so the app's startup (which opens Postgres) never runs.
    return TestClient(app)


def test_get_object_with_slashes_in_its_key(client):
    response = client.get("/api/objects/Facility/hospital/way/1")
    assert response.status_code == 200
    assert response.json()["name"] == "El Centro Regional Medical Center"


def test_links_from_object_with_slashes_in_its_key(client):
    response = client.get("/api/objects/Facility/shelter/node/3/links/county")
    assert response.status_code == 200
    assert [o["name"] for o in response.json()["data"]] == ["Los Angeles County"]


def test_plain_keys_still_work(client):
    assert client.get("/api/objects/County/06025").json()["name"] == "Imperial County"
    linked = client.get("/api/objects/County/06025/links/facilities?order_by=name").json()["data"]
    assert [o["facility_id"] for o in linked] == ["hospital/way/1", "school/node/2"]
