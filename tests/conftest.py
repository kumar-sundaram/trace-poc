import pytest

from api.config import Settings
from api.graph import GraphClient


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
