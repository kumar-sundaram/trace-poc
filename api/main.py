"""FastAPI application factory. One deployable, five modules (§5.2)."""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles

from api.admin import router as admin_router
from api.config import get_settings
from api.explore.router import router as explore_router
from api.ingestion.router import router as ingestion_router
from api.services import build_services
from api.signal.router import router as signal_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    services = build_services(get_settings())
    app.state.graph = services.graph
    app.state.signals = services.signals
    app.state.resolution = services.resolution
    app.state.explore = services.explore
    app.state.seeder = services.seeder
    yield
    services.graph.close()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="Party Network Platform POC",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.include_router(ingestion_router)
    app.include_router(signal_router)
    app.include_router(explore_router)
    app.include_router(admin_router)

    @app.get("/healthz")
    def healthz(request: Request) -> dict:
        return {
            "status": "ok",
            "neo4j": "ok" if request.app.state.graph.ping() else "unreachable",
            "knownSourceSystems": settings.known_source_systems,
            "roleVocabulary": settings.role_vocabulary,
        }

    # FR-22: the SPA is built statically and served by the api (§5). Routes
    # above win; the mount only catches what they don't.
    ui_dist = Path(__file__).resolve().parents[1] / "ui" / "dist"
    if ui_dist.is_dir():
        app.mount("/", StaticFiles(directory=ui_dist, html=True), name="ui")

    return app


app = create_app()
