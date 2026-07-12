"""Seed loader and demo reset (FR-24, FR-25).

Replays the curated CSV through the real ingestion path — validation,
idempotency, resolution, post-write signal evaluation — so the seeded graph
is exactly what production semantics produce, including the planted
duplicate being absorbed and the degree-guard exclusion. Rows load in CSV
order in one pass (the FANOUT_POSITIVE batch lands within one window).

CLI: uv run python -m api.seeding  (full reset: wipe graph + streams + load)
"""

import csv
import json
import logging
from time import perf_counter

from api.config import Settings, get_settings
from api.emitter.emitter import EventEmitter
from api.graph import GraphClient
from api.ingestion.models import PartyEvent
from api.resolve.service import ResolutionService

logger = logging.getLogger(__name__)


class SeedLoader:
    def __init__(
        self,
        graph: GraphClient,
        resolution: ResolutionService,
        emitter: EventEmitter,
        settings: Settings,
    ) -> None:
        self._graph = graph
        self._resolution = resolution
        self._emitter = emitter
        self._settings = settings

    def reset(self) -> dict:
        """FR-24: clear the graph and both streams, reload the seed."""
        cleared = self._graph.wipe()
        self._emitter.reset()
        summary = self.load()
        return {"clearedNodes": cleared, **summary}

    def load(self) -> dict:
        start = perf_counter()
        events = 0
        duplicates = 0
        with open(self._settings.seed_dataset_path) as f:
            for row in csv.DictReader(f):
                payload = {k: v for k, v in row.items() if k != "scenario" and v}
                event = PartyEvent(**payload)
                events += 1
                if self._resolution.is_already_processed(event):
                    duplicates += 1
                    continue
                self._resolution.resolve(event)

        counts = self._graph.execute_read(
            lambda tx: tx.run(
                "OPTIONAL MATCH (p:Party) WITH count(p) AS parties "
                "OPTIONAL MATCH (r:RawRecord) WITH parties, count(r) AS rawRecords "
                "OPTIONAL MATCH (s:Signal {status: 'RAISED'}) "
                "RETURN parties, rawRecords, count(s) AS raisedSignals"
            ).single()
        )
        summary = {
            "events": events,
            "duplicatesAbsorbed": duplicates,
            "parties": counts["parties"],
            "rawRecords": counts["rawRecords"],
            "raisedSignals": counts["raisedSignals"],
            "elapsedSeconds": round(perf_counter() - start, 2),
        }
        logger.info("seed loaded: %s", summary)
        return summary


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    from api.services import build_services

    settings = get_settings()
    services = build_services(settings)
    try:
        print(json.dumps(services.seeder.reset(), indent=2))
    finally:
        services.graph.close()


if __name__ == "__main__":
    main()
