"""Attribute fan-out rule and signal lifecycle (FR-17, FR-18, FR-19, FR-21)."""

import json
import logging

from tests.data import curated


def post_all(client, rows):
    for row in rows:
        resp = client.post("/events", json=row)
        assert resp.status_code == 202, resp.text


def signal_nodes(graph) -> list[dict]:
    return graph.execute_read(
        lambda tx: [
            dict(r)
            for r in tx.run(
                "MATCH (s:Signal) RETURN s.id AS id, s.patternType AS patternType, "
                "s.severity AS severity, s.status AS status, "
                "s.relatedPartyIds AS relatedPartyIds, s.causationEventId AS causation"
            )
        ]
    )


def signal_events(client) -> list[dict]:
    path = client.streams_dir / "signal.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines()]


class TestFanoutPositive:
    def test_three_parties_one_address_fires_once(self, clean_graph, app_client):
        rows = curated("FANOUT_POSITIVE")
        post_all(app_client, rows)

        [signal] = signal_nodes(clean_graph)
        assert signal["patternType"] == "attribute_fanout"
        assert signal["status"] == "RAISED"
        assert signal["severity"] == "MEDIUM"  # exactly N parties
        assert len(signal["relatedPartyIds"]) == 3
        # Raised while processing the third event — the causation reference
        assert signal["causation"] == rows[2]["eventId"]

        [event] = signal_events(app_client)
        assert event["eventType"] == "signal"
        assert event["payload"]["signalId"] == signal["id"]
        assert event["payload"]["causationEventId"] == rows[2]["eventId"]
        assert event["payload"]["evidencePath"][0].startswith("Property:")

    def test_redelivery_raises_no_duplicate(self, clean_graph, app_client):
        """FR-2 extends to signals: absorbing a duplicate event must not
        re-fire, and re-evaluating the same pattern state must not either."""
        rows = curated("FANOUT_POSITIVE")
        post_all(app_client, rows)
        app_client.post("/events", json=rows[2])  # duplicate delivery
        assert len(signal_nodes(clean_graph)) == 1
        assert len(signal_events(app_client)) == 1

    def test_two_parties_do_not_fire(self, clean_graph, app_client):
        post_all(app_client, curated("FANOUT_POSITIVE")[:2])
        assert signal_nodes(clean_graph) == []


class TestFanoutNegative:
    def test_high_connectivity_party_never_fires(self, clean_graph, app_client):
        """FR-25e: Patricia Morrison's breadth is legitimate exposure — six
        properties each with one party can't satisfy the fan-out pattern."""
        post_all(app_client, curated("HIGH_CONNECTIVITY_NEGATIVE"))
        assert signal_nodes(clean_graph) == []
        assert signal_events(app_client) == []

    def test_loans_outside_window_do_not_count(self, clean_graph, app_client):
        rows = curated("FANOUT_POSITIVE")
        post_all(app_client, rows)
        # Push one party's loan origination outside the 14-day window,
        # clear raised signals, and re-run: only 2 parties remain in-window.
        clean_graph.execute_write(
            lambda tx: tx.run(
                "MATCH (l:Loan {id: 'MF-811111'}) "
                "SET l.originatedAt = toString(datetime() - duration({days: 30}))"
            )
        )
        clean_graph.execute_write(lambda tx: tx.run("MATCH (s:Signal) DETACH DELETE s"))
        result = app_client.post("/admin/signals/rerun").json()
        assert result["raised"] == 0
        assert signal_nodes(clean_graph) == []


class TestDegreeGuard:
    def test_common_attribute_excluded_and_logged(self, clean_graph, app_client, caplog):
        """FR-21: 250 registrations at one agent address. The rule fires once
        while the address is still below the guard threshold (legitimate at
        the time); once the guard trips, the attribute is excluded from
        evaluation and the earlier signal is reclassified — end state has no
        RAISED signal and the exclusion is logged."""
        rows = curated("DEGREE_GUARD")
        assert len(rows) == 250
        with caplog.at_level(logging.WARNING, logger="api.signal.service"):
            post_all(app_client, rows)
        assert "excluded-common-attribute" in caplog.text
        statuses = [s["status"] for s in signal_nodes(clean_graph)]
        assert "RAISED" not in statuses
        assert statuses.count("EXCLUDED_DEGREE_GUARD") <= 1
        assert app_client.get("/signals").json() == []


class TestAdminRerun:
    def test_rerun_reraises_deterministically(self, clean_graph, app_client):
        rows = curated("FANOUT_POSITIVE")
        post_all(app_client, rows)
        [original] = signal_nodes(clean_graph)

        clean_graph.execute_write(lambda tx: tx.run("MATCH (s:Signal) DETACH DELETE s"))
        result = app_client.post("/admin/signals/rerun").json()
        assert result["raised"] == 1
        [reraised] = signal_nodes(clean_graph)
        # Same pattern state → same deterministic signal id
        assert reraised["id"] == original["id"]
        assert reraised["causation"].startswith("rerun-")

    def test_rerun_is_idempotent_when_nothing_changed(self, clean_graph, app_client):
        post_all(app_client, curated("FANOUT_POSITIVE"))
        result = app_client.post("/admin/signals/rerun").json()
        assert result["raised"] == 0  # signal already exists for this state
        assert len(signal_nodes(clean_graph)) == 1


class TestSignalListing:
    def test_signals_endpoint_lists_raised(self, clean_graph, app_client):
        post_all(app_client, curated("FANOUT_POSITIVE"))
        [listed] = app_client.get("/signals").json()
        assert listed["patternType"] == "attribute_fanout"
        assert listed["status"] == "RAISED"
        assert len(listed["relatedPartyIds"]) == 3
        assert listed["raisedAt"]
