"""FastAPI application factory. One deployable, five modules (§5.2)."""

from fastapi import FastAPI

from api.config import get_settings


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="Party Network Platform POC",
        version="0.1.0",
    )

    @app.get("/healthz")
    def healthz() -> dict:
        return {
            "status": "ok",
            "knownSourceSystems": settings.known_source_systems,
            "roleVocabulary": settings.role_vocabulary,
        }

    return app


app = create_app()
