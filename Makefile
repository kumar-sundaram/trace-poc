# Single-command startup per process (G6, NFR-4)
.PHONY: db db-stop run test lint

db:            ## start local Neo4j (brew-installed)
	neo4j start

db-stop:
	neo4j stop

run:           ## start the FastAPI app
	uv run uvicorn api.main:app --reload

test:
	uv run pytest

lint:
	uv run ruff check .
