"""FR-22: the built SPA is served statically by the api process (§5)."""

from pathlib import Path

import pytest

UI_DIST = Path(__file__).resolve().parents[1] / "ui" / "dist"


@pytest.mark.skipif(not UI_DIST.is_dir(), reason="ui not built (make ui)")
class TestStaticServing:
    def test_root_serves_spa(self, app_client):
        resp = app_client.get("/")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]
        assert "Party Network POC" in resp.text

    def test_api_routes_win_over_mount(self, app_client):
        assert app_client.get("/healthz").json()["status"] == "ok"
        assert app_client.get("/signals").status_code == 200
