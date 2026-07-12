import pytest
from fastapi.testclient import TestClient

from api.config import Settings
from api.graph import GraphClient
from api.main import create_app


def test_healthz():
    probe = GraphClient(Settings())
    try:
        probe.verify_connectivity()
    except Exception:
        pytest.skip("local Neo4j is not reachable (make db)")
    finally:
        probe.close()

    # Context manager runs the lifespan: connect, bootstrap schema.
    with TestClient(create_app()) as client:
        resp = client.get("/healthz")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["neo4j"] == "ok"
    assert "LoanSphere_Origination" in body["knownSourceSystems"]
