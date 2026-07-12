import pytest
from fastapi.testclient import TestClient

from api.config import Settings, get_settings
from api.graph import GraphClient
from api.main import create_app

_bedrock_status: dict = {}


def bedrock_available() -> bool:
    """Probe once per session whether Bedrock embeddings are callable."""
    if "ok" not in _bedrock_status:
        from api.resolve.adapters import build_embedding_client

        try:
            build_embedding_client(Settings()).embed("probe")
            _bedrock_status["ok"] = True
        except Exception:
            _bedrock_status["ok"] = False
    return _bedrock_status["ok"]


@pytest.fixture(scope="session")
def graph() -> GraphClient:
    """A GraphClient against the local Neo4j; skips the test if it isn't running."""
    client = GraphClient(Settings())
    try:
        client.verify_connectivity()
    except Exception:
        pytest.skip("local Neo4j is not reachable (make db)")
    client.bootstrap_schema()
    yield client
    client.close()


@pytest.fixture()
def clean_graph(graph: GraphClient) -> GraphClient:
    """Wipe all data (schema survives) for scenario tests that count nodes."""
    graph.execute_write(lambda tx: tx.run("MATCH (n) DETACH DELETE n"))
    return graph


def _make_client(tmp_path, monkeypatch, extra_env: dict[str, str]):
    monkeypatch.setenv("TRACE_STREAMS__DIRECTORY", str(tmp_path / "streams"))
    for key, value in extra_env.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    client = TestClient(create_app())
    client.streams_dir = tmp_path / "streams"
    return client


@pytest.fixture()
def app_client(graph, tmp_path, monkeypatch):
    """App on the deterministic hash embedder — hermetic, no credentials."""
    with _make_client(
        tmp_path, monkeypatch, {"TRACE_EMBEDDING__ADAPTER": "hash"}
    ) as client:
        yield client
    get_settings.cache_clear()


@pytest.fixture()
def bedrock_client(graph, tmp_path, monkeypatch):
    """App on real Titan embeddings — thresholds are calibrated to these scores."""
    if not bedrock_available():
        pytest.skip("Bedrock embeddings not reachable (AWS credentials required)")
    with _make_client(tmp_path, monkeypatch, {}) as client:
        yield client
    get_settings.cache_clear()
