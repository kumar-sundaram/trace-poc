# Party Network Platform (Trace POC)

A proof-of-concept for a graph-based party network: tiered identity resolution, cross-system exposure traversal, and pattern-based signal detection on a single Neo4j knowledge graph.

[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)

## Status

This repository is **spec-driven and under active development**. The requirements specification and synthetic test fixtures are in place; application code (FastAPI backend, React UI, Neo4j integration) is being built against the spec.

| Artifact | Location |
|---|---|
| Requirements spec (source of truth) | [`spec/party-network-poc-spec.md`](spec/party-network-poc-spec.md) |
| Synthetic test data | [`docs/test-data/`](docs/test-data/) |
| Contributor guide | [`CONTRIBUTING.md`](CONTRIBUTING.md) |

## What this POC demonstrates

- **Tiered party resolution** — deterministic match → vector similarity → LLM disambiguation, writing to one graph
- **Cross-system ingestion** — multiple simulated upstream systems converge idempotently on shared party nodes
- **Exposure lookup** — read-only traversal across roles, properties, and loans
- **Signal detection** — pattern rules (e.g., attribute fan-out) emit advisory events post-write
- **Full auditability** — every node, edge, and match decision carries provenance (`sourceSystem`, `eventId`, tier, method)

All seed data is **synthetic** — no real names, addresses, or identifiers.

## Architecture

```
api (FastAPI modular monolith)
├── ingestion/   — validate and normalize tagged party events
├── resolve/     — tiered matching pipeline, transactional graph writes
├── explore/     — read-only traversal queries
├── signal/      — pattern rule evaluation post-write
└── emitter/     — publish resolution-outcome and signal events

ui (React SPA, served statically by the API)
neo4j (Community Edition 5.x, standard Cypher only)
```

Write path: REST event → `202` ack → resolve → ACID graph write → signal evaluation → event streams.

Read path: Explore endpoints — no writes, no rule triggers.

See the [spec](spec/party-network-poc-spec.md) for the full graph model, functional requirements, and acceptance walkthrough.

## Prerequisites

When the application is available:

- Python 3.12+
- Neo4j Community Edition 5.x
- Node.js 18+ (for UI build)

The POC runs locally as **two processes** (app + Neo4j), each started with a single command. No external API credentials are required — LLM and embedding clients use deterministic local/mock implementations.

## Quick start (test data)

Regenerate synthetic CSV fixtures:

```bash
python docs/test-data/generate_parties.py
```

Requires `faker`:

```bash
pip install faker
```

See [`docs/test-data/README.md`](docs/test-data/README.md) for fixture descriptions and planted acceptance scenarios.

## Repository layout

```
trace-poc/
├── spec/                  # Requirements specification
├── docs/
│   └── test-data/         # Seed CSVs, negative fixtures, generator
├── CONTRIBUTING.md
├── CODE_OF_CONDUCT.md
├── SECURITY.md
└── LICENSE
```

Application directories (`api/`, `ui/`) will be added as implementation proceeds.

## Contributing

Contributions are welcome. Please read [CONTRIBUTING.md](CONTRIBUTING.md) before opening a pull request. The spec is the source of truth — changes to behavior should start there or align with it.

## Security

Report vulnerabilities privately — see [SECURITY.md](SECURITY.md).

## License

Licensed under the [Apache License, Version 2.0](LICENSE).
