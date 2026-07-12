"""§8 acceptance walkthrough, automated end to end.

Steps run in order against one freshly seeded app (real Bedrock embeddings —
skipped without credentials). Each test is one numbered step of the spec's
demo script; `state` carries facts between steps exactly as a human demo
would carry them in their head.

Note on step 2: the spec sketches "a Tier 2/3 match" for the Jon A. Smith
variant. Under the calibrated pipeline the variant resolves via the Tier-3
band and is confirmed at T4 (auto-match requires exact name equality — see
CLAUDE.md); the substance of the step — the variant joins the existing
mastered party, with tier and confidence reported — is asserted strictly.
"""

import json
import logging
import os

import pytest
from fastapi.testclient import TestClient

from api.config import get_settings
from api.emitter.contracts import EventEnvelope
from tests.conftest import bedrock_available

pytestmark = pytest.mark.acceptance


@pytest.fixture(scope="module")
def demo(graph, tmp_path_factory):
    """Step 1: app up, healthy, seed loaded."""
    if not bedrock_available():
        pytest.skip("Bedrock embeddings not reachable (AWS credentials required)")
    streams = tmp_path_factory.mktemp("streams")
    os.environ["TRACE_STREAMS__DIRECTORY"] = str(streams)
    get_settings.cache_clear()
    from api.main import create_app

    with TestClient(create_app()) as client:
        client.streams_dir = streams
        seed_summary = client.post("/admin/reset").json()
        yield client, seed_summary, {}
    del os.environ["TRACE_STREAMS__DIRECTORY"]
    get_settings.cache_clear()


def outcomes(client) -> list[dict]:
    path = client.streams_dir / "resolution-outcome.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_step1_healthy_and_seeded(demo):
    client, seed_summary, _ = demo
    health = client.get("/healthz").json()
    assert health["status"] == "ok"
    assert health["neo4j"] == "ok"
    assert seed_summary["parties"] == 262
    assert seed_summary["duplicatesAbsorbed"] == 1
    assert seed_summary["raisedSignals"] == 1


def test_step2_variant_submission_resolves_with_confidence(demo):
    client, _, state = demo
    resp = client.post(
        "/events",
        json={
            "sourceSystem": "LoanSphere_Origination",
            "eventId": "demo-jon-variant",
            "partyType": "INDIVIDUAL",
            "firstName": "Jon A.",
            "lastName": "Smith",
            "address": "123 Main St, Atlanta, GA 30303",
            "role": "BORROWER",
            "loanRef": "MF-DEMO-01",
        },
    )
    assert resp.status_code == 202
    assert resp.json()["correlation"] == {
        "sourceSystem": "LoanSphere_Origination",
        "eventId": "demo-jon-variant",
    }

    [outcome] = [o for o in outcomes(client) if o["eventId"] == "demo-jon-variant"]
    payload = outcome["payload"]
    assert payload["created"] is False  # joined the existing mastered party
    assert payload["matchTier"] in ("T2", "T3", "T4")
    assert 0 < payload["confidence"] <= 1
    state["jonPartyId"] = payload["masteredPartyId"]

    # It is the same party the seeded Jonathan Smith cluster resolved to
    cluster = [
        o["payload"]["masteredPartyId"]
        for o in outcomes(client)
        if o["payload"]["aliasName"] in ("JONATHAN SMITH", "JON A SMITH")
    ]
    assert set(cluster) == {state["jonPartyId"]}


def test_step3_borrower_without_address_rejected(demo):
    client, _, _ = demo
    resp = client.post(
        "/events",
        json={
            "sourceSystem": "LoanSphere_Origination",
            "eventId": "demo-no-address",
            "partyType": "INDIVIDUAL",
            "firstName": "No",
            "lastName": "Address",
            "role": "BORROWER",
            "loanRef": "MF-DEMO-02",
        },
    )
    assert resp.status_code == 422
    assert "address" in resp.text.lower()  # a clear validation error


def test_step4_new_role_from_different_source_same_party(demo):
    client, _, state = demo
    resp = client.post(
        "/events",
        json={
            "sourceSystem": "ServicingMaster_Pro",
            "eventId": "demo-jon-sponsor",
            "partyType": "INDIVIDUAL",
            "firstName": "Jon A.",
            "lastName": "Smith",
            "address": "123 Main St, Atlanta, GA 30303",
            "role": "SPONSOR",
            "loanRef": "MF-DEMO-03",
        },
    )
    assert resp.status_code == 202
    [outcome] = [o for o in outcomes(client) if o["eventId"] == "demo-jon-sponsor"]
    assert outcome["payload"]["masteredPartyId"] == state["jonPartyId"]  # same party ID

    result = client.get(
        "/explore", params={"anchorType": "party", "q": state["jonPartyId"]}
    ).json()
    demo_roles = {
        (e["role"], e["sourceSystem"])
        for e in result["edges"]
        if e["type"] == "HAS_ROLE_ON" and e["target"].startswith("MF-DEMO")
    }
    assert demo_roles == {
        ("BORROWER", "LoanSphere_Origination"),
        ("SPONSOR", "ServicingMaster_Pro"),
    }
    state["edgeCount"] = len(result["edges"])


def test_step5_exact_redelivery_absorbed(demo):
    client, _, state = demo
    resp = client.post(
        "/events",
        json={
            "sourceSystem": "ServicingMaster_Pro",
            "eventId": "demo-jon-sponsor",
            "partyType": "INDIVIDUAL",
            "firstName": "Jon A.",
            "lastName": "Smith",
            "address": "123 Main St, Atlanta, GA 30303",
            "role": "SPONSOR",
            "loanRef": "MF-DEMO-03",
        },
    )
    assert resp.status_code == 202
    assert resp.json()["duplicate"] is True
    result = client.get(
        "/explore", params={"anchorType": "party", "q": state["jonPartyId"]}
    ).json()
    assert len(result["edges"]) == state["edgeCount"]  # no duplicate edges
    assert len([o for o in outcomes(client) if o["eventId"] == "demo-jon-sponsor"]) == 1


def test_step6_high_connectivity_party_full_exposure_no_signal(demo):
    client, _, _ = demo
    result = client.get(
        "/explore", params={"anchorType": "party", "q": "Patricia Morrison"}
    ).json()
    roles = [e for e in result["edges"] if e["type"] == "HAS_ROLE_ON"]
    assert len(roles) == 6
    assert {e["role"] for e in roles} == {
        "BORROWER", "KEY_BORROWER_PRINCIPAL", "SPONSOR",
    }
    assert result["flags"] == []


def test_step7_fanout_party_shows_signal_and_flag(demo):
    client, _, _ = demo
    result = client.get(
        "/explore", params={"anchorType": "party", "q": "Alpha 100 LLC"}
    ).json()
    shared = [n for n in result["nodes"] if n["nodeType"] == "Property"]
    assert any("777 RISK AVE" in n["id"] for n in shared)
    anchor_id = result["anchor"]["id"]
    assert any(f["partyId"] == anchor_id for f in result["flags"])
    assert all(set(f) == {"partyId", "signalId", "patternType"} for f in result["flags"])

    panel = client.get("/signals").json()
    assert any(
        s["patternType"] == "attribute_fanout" and anchor_id in s["relatedPartyIds"]
        for s in panel
    )


def test_step8_high_degree_attribute_guarded_and_logged(demo, caplog):
    client, _, _ = demo
    result = client.get(
        "/explore",
        params={
            "anchorType": "property",
            "q": "Corporation Trust Center, 1209 Orange St, Wilmington, DE 19801",
        },
    ).json()
    [guard] = result["guards"]
    assert guard["expanded"] is False
    assert guard["degree"] == 250
    assert len(result["nodes"]) == 1  # summary marker, not thousands of paths

    with caplog.at_level(logging.WARNING, logger="api.signal.service"):
        client.post("/admin/signals/rerun")
    assert "excluded-common-attribute" in caplog.text


def test_step9_streams_match_contracts_and_correlate(demo):
    client, _, _ = demo
    outcome_lines = (client.streams_dir / "resolution-outcome.jsonl").read_text().splitlines()
    signal_lines = (client.streams_dir / "signal.jsonl").read_text().splitlines()
    assert outcome_lines and signal_lines

    known_events = {
        (o["sourceSystem"], o["eventId"])
        for o in (json.loads(line) for line in outcome_lines)
    }
    for line in outcome_lines + signal_lines:
        envelope = EventEnvelope.model_validate_json(line)  # schema conformance
        assert envelope.schemaVersion == "1.0.0"
    # 273 seed events + 2 demo submissions, each exactly once
    assert len(outcome_lines) == 275
    assert ("LoanSphere_Origination", "demo-jon-variant") in known_events
    # Signal events correlate back through the causation reference
    for line in signal_lines:
        payload = json.loads(line)["payload"]
        assert payload["causationEventId"]
