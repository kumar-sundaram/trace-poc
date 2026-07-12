"""FastAPI application factory. One deployable, five modules (§5.2)."""

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request

from api.config import get_settings
from api.emitter.emitter import build_emitter
from api.graph import GraphClient
from api.ingestion.router import router as ingestion_router
from api.resolve.adapters import build_embedding_client, build_llm_client
from api.resolve.service import ResolutionService


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    graph = GraphClient(settings)
    graph.verify_connectivity()
    graph.bootstrap_schema()
    app.state.graph = graph
    app.state.resolution = ResolutionService(
        graph=graph,
        settings=settings,
        embedding_client=build_embedding_client(settings),
        llm_client=build_llm_client(settings),
        emitter=build_emitter(settings),
    )
    yield
    graph.close()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="Party Network Platform POC",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.include_router(ingestion_router)

    @app.get("/healthz")
    def healthz(request: Request) -> dict:
        return {
            "status": "ok",
            "neo4j": "ok" if request.app.state.graph.ping() else "unreachable",
            "knownSourceSystems": settings.known_source_systems,
            "roleVocabulary": settings.role_vocabulary,
        }

    return app


app = create_app()
