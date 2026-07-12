"""Graph layer: schema bootstrap (FR-10), ACID write helper (NFR-2)."""

import uuid

import pytest
from neo4j.exceptions import ClientError

from api.graph import VECTOR_INDEX_NAME, GraphClient


def test_bootstrap_is_idempotent(graph: GraphClient):
    graph.bootstrap_schema()  # second run on top of the fixture's — must not raise
    graph.bootstrap_schema()


def test_uniqueness_constraints_exist(graph: GraphClient):
    def constrained_labels(tx):
        result = tx.run("SHOW CONSTRAINTS YIELD labelsOrTypes, properties, type RETURN *")
        return {
            record["labelsOrTypes"][0]
            for record in result
            if "UNIQUENESS" in record["type"] and record["properties"] == ["id"]
        }

    labels = graph.execute_read(constrained_labels)
    assert {"Party", "Property", "Loan", "RawRecord", "Signal"} <= labels


def test_lookup_and_vector_indexes_exist(graph: GraphClient):
    def indexes(tx):
        result = tx.run("SHOW INDEXES YIELD name, type, options RETURN *")
        return {record["name"]: record for record in result}

    idx = graph.execute_read(indexes)
    assert "party_normalized_name" in idx
    assert "property_normalized_address" in idx
    from api.config import Settings

    vector = idx[VECTOR_INDEX_NAME]
    assert vector["type"] == "VECTOR"
    assert (
        vector["options"]["indexConfig"]["vector.dimensions"]
        == Settings().embedding.dimension
    )


def test_duplicate_party_id_rejected(graph: GraphClient):
    party_id = f"test-{uuid.uuid4()}"

    def create_twice(tx):
        tx.run("CREATE (:Party {id: $id})", id=party_id)
        tx.run("CREATE (:Party {id: $id})", id=party_id)

    try:
        with pytest.raises(ClientError):
            graph.execute_write(create_twice)
    finally:
        graph.execute_write(
            lambda tx: tx.run("MATCH (p:Party {id: $id}) DELETE p", id=party_id)
        )


def test_write_transaction_is_all_or_nothing(graph: GraphClient):
    """NFR-2: a failure mid-transaction must leave nothing behind."""
    party_id = f"test-{uuid.uuid4()}"

    def create_then_fail(tx):
        tx.run("CREATE (:Party {id: $id})", id=party_id)
        raise RuntimeError("forced failure after first write")

    with pytest.raises(RuntimeError):
        graph.execute_write(create_then_fail)

    def count(tx):
        return tx.run(
            "MATCH (p:Party {id: $id}) RETURN count(p) AS n", id=party_id
        ).single()["n"]

    assert graph.execute_read(count) == 0
