from fastapi.testclient import TestClient

from api.main import create_app


def test_healthz():
    client = TestClient(create_app())
    resp = client.get("/healthz")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert "LoanSphere_Origination" in body["knownSourceSystems"]
