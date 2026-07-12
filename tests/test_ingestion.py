"""Ingestion contract, endpoint, and idempotency (FR-1, FR-2, FR-8).

Validation cases come from docs/test-data/party_network_negative.csv;
the idempotency case is the IDEMPOTENCY_DUPLICATE row of the curated CSV.
Runs on the hash embedder — contract behavior is adapter-independent.
"""

import uuid

import pytest

from tests.data import curated, load_rows


@pytest.fixture()
def fresh_event() -> dict:
    """A valid borrower event with a unique eventId."""
    return {
        "sourceSystem": "LoanSphere_Origination",
        "eventId": f"test-{uuid.uuid4()}",
        "partyType": "INDIVIDUAL",
        "firstName": "Ingest",
        "lastName": "Tester",
        "address": "1 Test Plaza, Testville, TX 75001",
        "role": "BORROWER",
        "loanRef": "MF-TEST01",
    }


@pytest.fixture(autouse=True)
def cleanup_test_records(graph):
    yield
    graph.execute_write(
        lambda tx: tx.run(
            "MATCH (r:RawRecord) WHERE r.eventId STARTS WITH 'test-' "
            "OPTIONAL MATCH (r)-[:RESOLVES_TO]->(p:Party) DETACH DELETE r, p"
        )
    )


class TestValidationRejects:
    def test_all_negative_csv_rows_rejected(self, app_client):
        rows = load_rows("party_network_negative.csv")
        assert len(rows) == 3
        for row in rows:
            resp = app_client.post("/events", json=row)
            assert resp.status_code == 422, f"expected reject for {row}"

    def test_role_outside_vocabulary_rejected(self, app_client, fresh_event):
        fresh_event["role"] = "MADE_UP_ROLE"
        assert app_client.post("/events", json=fresh_event).status_code == 422

    def test_unknown_source_system_rejected(self, app_client, fresh_event):
        fresh_event["sourceSystem"] = "Unknown_System"
        assert app_client.post("/events", json=fresh_event).status_code == 422

    def test_role_without_loan_ref_rejected(self, app_client, fresh_event):
        del fresh_event["loanRef"]
        assert app_client.post("/events", json=fresh_event).status_code == 422

    def test_no_partial_processing_on_reject(self, app_client, graph, fresh_event):
        """FR-8: a rejected event leaves nothing behind."""
        fresh_event.pop("address")  # borrower without address → 422
        assert app_client.post("/events", json=fresh_event).status_code == 422
        count = graph.execute_read(
            lambda tx: tx.run(
                "MATCH (r:RawRecord {eventId: $eid}) RETURN count(r) AS n",
                eid=fresh_event["eventId"],
            ).single()["n"]
        )
        assert count == 0


class TestAccept:
    def test_valid_event_gets_202_with_correlation(self, app_client, fresh_event):
        resp = app_client.post("/events", json=fresh_event)
        assert resp.status_code == 202
        body = resp.json()
        assert body["status"] == "accepted"
        assert body["duplicate"] is False
        assert body["correlation"] == {
            "sourceSystem": fresh_event["sourceSystem"],
            "eventId": fresh_event["eventId"],
        }
        # FR-8: no resolution outcome in the response
        assert "masteredPartyId" not in body

    def test_non_borrower_without_address_accepted(self, app_client, fresh_event):
        # ADDRESS_LESS_CONFIDENCE: sponsors may arrive address-less (§4.1)
        fresh_event.pop("address")
        fresh_event["role"] = "SPONSOR"
        assert app_client.post("/events", json=fresh_event).status_code == 202

    def test_raw_record_written_with_provenance(self, app_client, graph, fresh_event):
        app_client.post("/events", json=fresh_event)
        record = graph.execute_read(
            lambda tx: tx.run(
                "MATCH (r:RawRecord {eventId: $eid}) RETURN r", eid=fresh_event["eventId"]
            ).single()["r"]
        )
        assert record["sourceSystem"] == "LoanSphere_Origination"
        assert record["normalizedName"] == "INGEST TESTER"
        assert record["normalizedAddress"] == "1 TEST PLZ TESTVILLE TX 75001"
        assert record["receivedAt"]


class TestIdempotency:
    def test_redelivery_absorbed(self, app_client, graph, fresh_event):
        first = app_client.post("/events", json=fresh_event)
        second = app_client.post("/events", json=fresh_event)
        assert first.status_code == second.status_code == 202
        assert first.json()["duplicate"] is False
        assert second.json()["duplicate"] is True
        count = graph.execute_read(
            lambda tx: tx.run(
                "MATCH (r:RawRecord {eventId: $eid}) RETURN count(r) AS n",
                eid=fresh_event["eventId"],
            ).single()["n"]
        )
        assert count == 1

    def test_curated_duplicate_pair_shares_raw_record_id(self):
        """The curated CSV's planted duplicate must map to one RawRecord id."""
        cluster = curated("T2_VARIANT_CLUSTER")
        duplicate = curated("IDEMPOTENCY_DUPLICATE")
        original = next(r for r in cluster if r["eventId"] == duplicate[0]["eventId"])
        assert (
            f"{original['sourceSystem']}:{original['eventId']}"
            == f"{duplicate[0]['sourceSystem']}:{duplicate[0]['eventId']}"
        )
