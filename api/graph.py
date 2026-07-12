"""Neo4j graph layer: driver lifecycle, transaction helpers, schema bootstrap.

Standard Cypher only — no APOC, no GDS (NFR-2). Multi-write resolutions must
run through a single managed transaction (execute_write), all-or-nothing.
"""

import logging
from collections.abc import Callable
from typing import Any

from neo4j import Driver, GraphDatabase, ManagedTransaction, Session

from api.config import Settings

logger = logging.getLogger(__name__)

# FR-10: uniqueness on each label's id, indexes on the two lookup properties,
# plus the Tier-3 vector index over Party embeddings. All idempotent.
SCHEMA_STATEMENTS: tuple[str, ...] = (
    "CREATE CONSTRAINT party_id_unique IF NOT EXISTS "
    "FOR (n:Party) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT property_id_unique IF NOT EXISTS "
    "FOR (n:Property) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT loan_id_unique IF NOT EXISTS "
    "FOR (n:Loan) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT raw_record_id_unique IF NOT EXISTS "
    "FOR (n:RawRecord) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT signal_id_unique IF NOT EXISTS "
    "FOR (n:Signal) REQUIRE n.id IS UNIQUE",
    "CREATE INDEX party_normalized_name IF NOT EXISTS "
    "FOR (n:Party) ON (n.normalizedName)",
    "CREATE INDEX property_normalized_address IF NOT EXISTS "
    "FOR (n:Property) ON (n.normalizedAddress)",
)

VECTOR_INDEX_NAME = "party_embedding"

VECTOR_INDEX_STATEMENT = (
    f"CREATE VECTOR INDEX {VECTOR_INDEX_NAME} IF NOT EXISTS "
    "FOR (n:Party) ON (n.embedding) "
    "OPTIONS {indexConfig: {"
    "`vector.dimensions`: $dimension, "
    "`vector.similarity_function`: 'cosine'}}"
)


class GraphClient:
    def __init__(self, settings: Settings) -> None:
        self._driver: Driver = GraphDatabase.driver(
            settings.neo4j.uri,
            auth=(settings.neo4j.user, settings.neo4j.password),
        )
        self._database = settings.neo4j.database
        self._embedding_dimension = settings.embedding.dimension

    def verify_connectivity(self) -> None:
        self._driver.verify_connectivity()

    def session(self) -> Session:
        return self._driver.session(database=self._database)

    def execute_write(self, work: Callable[[ManagedTransaction], Any]) -> Any:
        """Run `work` in one managed write transaction (NFR-2: all-or-nothing)."""
        with self.session() as session:
            return session.execute_write(work)

    def execute_read(self, work: Callable[[ManagedTransaction], Any]) -> Any:
        with self.session() as session:
            return session.execute_read(work)

    def bootstrap_schema(self) -> None:
        with self.session() as session:
            for statement in SCHEMA_STATEMENTS:
                session.run(statement).consume()
            session.run(
                VECTOR_INDEX_STATEMENT, dimension=self._embedding_dimension
            ).consume()
        logger.info(
            "graph schema bootstrapped (%d constraints/indexes + vector index %s, dim=%d)",
            len(SCHEMA_STATEMENTS),
            VECTOR_INDEX_NAME,
            self._embedding_dimension,
        )

    def ping(self) -> bool:
        try:
            with self.session() as session:
                session.run("RETURN 1").consume()
            return True
        except Exception:
            return False

    def close(self) -> None:
        self._driver.close()
