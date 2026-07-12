# Single-command startup per process (G6, NFR-4)
.PHONY: db db-stop run test lint seed ui

db:            ## start local Neo4j (brew-installed)
	neo4j start

db-stop:
	neo4j stop

run:           ## start the FastAPI app
	uv run uvicorn api.main:app --reload

seed:          ## reset graph + streams and load the curated dataset
	uv run python -m api.seeding

ui:            ## build the SPA (served statically by the api)
	cd ui && npm install && npm run build

test:
	uv run pytest

lint:
	uv run ruff check .
