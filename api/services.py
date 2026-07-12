"""Composition root: builds the wired service set for the app and the CLI."""

from dataclasses import dataclass

from api.config import Settings
from api.emitter.emitter import EventEmitter, build_emitter
from api.explore.service import ExploreService
from api.graph import GraphClient
from api.resolve.adapters import build_embedding_client, build_llm_client
from api.resolve.service import ResolutionService
from api.seeding import SeedLoader
from api.signal.service import SignalService


@dataclass
class Services:
    graph: GraphClient
    emitter: EventEmitter
    signals: SignalService
    resolution: ResolutionService
    explore: ExploreService
    seeder: SeedLoader


def build_services(settings: Settings) -> Services:
    graph = GraphClient(settings)
    graph.verify_connectivity()
    graph.bootstrap_schema()
    emitter = build_emitter(settings)
    signals = SignalService(graph, settings, emitter)
    resolution = ResolutionService(
        graph=graph,
        settings=settings,
        embedding_client=build_embedding_client(settings),
        llm_client=build_llm_client(settings),
        emitter=emitter,
        post_write_hook=signals.evaluate_event,
    )
    return Services(
        graph=graph,
        emitter=emitter,
        signals=signals,
        resolution=resolution,
        explore=ExploreService(graph, settings),
        seeder=SeedLoader(graph, resolution, emitter, settings),
    )
