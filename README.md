# Party Network Platform (Trace POC)

A proof-of-concept for a graph-based party network: tiered identity resolution, cross-system exposure traversal, and pattern-based signal detection on a single Neo4j knowledge graph.

[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)

## Status

**Implemented.** All functional requirements of the spec are built and covered by an automated test suite, including the full [§8 acceptance walkthrough](spec/party-network-poc-spec.md#8-acceptance-walkthrough-demo-script).

| Artifact | Location |
|---|---|
| Requirements spec (source of truth) | [`spec/party-network-poc-spec.md`](spec/party-network-poc-spec.md) |
| Boundary contracts (ingestion + outbound events) | [`docs/contracts/`](docs/contracts/) |
| Synthetic test data / acceptance fixture | [`docs/test-data/`](docs/test-data/) |
| NFR-7 scale probe results (100k parties / 1M rels) | [`docs/scale-probe-results.md`](docs/scale-probe-results.md) |
| Contributor guide | [`CONTRIBUTING.md`](CONTRIBUTING.md) |

## What this POC demonstrates

- **Tiered party resolution** — exact identifier → normalized name+address → vector similarity → LLM disambiguation, writing to one graph
- **Cross-system ingestion** — multiple simulated upstream systems converge idempotently on shared party nodes
- **Exposure lookup** — read-only traversal across roles, properties, and loans, with a degree guard against supernodes
- **Signal detection** — an attribute fan-out rule emits advisory events post-write; signals advise, humans decide
- **Full auditability** — every node, edge, and match decision carries provenance (`sourceSystem`, `eventId`, tier, method)

All seed data is **synthetic** — no real names, addresses, or identifiers.

## Architecture

```
api (FastAPI modular monolith)
├── ingestion/   — validate and normalize tagged party events
├── resolve/     — tiered matching pipeline, transactional graph writes
├── explore/     — read-only traversal queries
├── signal/      — pattern rule evaluation post-write
└── emitter/     — publish resolution-outcome and signal events (JSONL streams)

ui (React SPA, built statically, served by the API)
neo4j (Community Edition, standard Cypher only — no APOC/GDS)
```

Write path: REST event → `202` ack → resolve → single ACID graph write → signal evaluation → event streams.
Read path: Explore — no writes, no rule triggers.

The LLM and embedding clients sit behind ports. Defaults: **Amazon Bedrock Titan Embed v2** for Tier-3 vectors (needs AWS credentials) and a **deterministic mock** for Tier-4 disambiguation. A credential-less hash embedder is one env var away (`TRACE_EMBEDDING__ADAPTER=hash`), so the system runs fully offline.

## Prerequisites

- Python 3.12+ and [`uv`](https://docs.astral.sh/uv/) (`brew install uv`)
- Neo4j Community Edition (`brew install neo4j`)
- Node.js 18+ (UI build only)
- AWS credentials with Bedrock access in `us-east-1` (optional — see hash fallback above)

## Setup and run

One-time setup:

```bash
uv sync                                            # Python deps
neo4j-admin dbms set-initial-password trace-poc-dev  # before first start
make ui                                            # build the SPA
```

Two processes, one command each (NFR-4):

```bash
make db      # neo4j start
make run     # uvicorn api.main:app  →  http://localhost:8000
```

Load the demo dataset (curated seed, replayed through the real ingestion path):

```bash
make seed    # or: POST /admin/reset — ~3½ min on Bedrock, seconds on the hash adapter
```

All tunables (thresholds, windows, degree guard, role vocabulary, source systems, adapters) live in [`config/settings.yaml`](config/settings.yaml), overridable via `TRACE_*` env vars (`__` for nesting).

## Demo script (§8)

With the app seeded, at http://localhost:8000:

1. **Health + seed** — `GET /healthz` reports app and Neo4j ok; seed summary shows 262 parties, 1 raised signal, 1 duplicate absorbed.
2. **Variant resolution** — `POST /events` with a "Jon A. Smith" borrower variant (address `123 Main St, Atlanta, GA 30303`) → `202` + correlation reference; the `data/streams/resolution-outcome.jsonl` event shows it joining the existing Jonathan Smith party with tier and confidence.
3. **Contract rejection** — the same event without an address → `422`, nothing written.
4. **Cross-source role aggregation** — same person as `SPONSOR` on a new loan from `ServicingMaster_Pro` → same mastered party ID; the UI shows one node with both role edges labeled by source system.
5. **Idempotency** — re-send the exact same event → `duplicate: true`, no new edges or outcome events.
6. **Legitimate breadth** — search **Patricia Morrison** in the UI → six loans across three roles, no signal flag.
7. **Fan-out signal** — search **Alpha 100 LLC** → shared address with two other LLCs, red flag on the parties, signal in the panel.
8. **Degree guard** — search the property `Corporation Trust Center, 1209 Orange St, Wilmington, DE 19801` → a summary marker (`degree: 250, expanded: false`) instead of 250 paths; `excluded-common-attribute` appears in the app log.
9. **Contracts** — every line of both stream files validates against the [published schemas](docs/contracts/) and correlates back to its originating request.

The same walkthrough runs as code: `uv run pytest tests/test_acceptance.py`.

## Tests

```bash
make test                                        # full suite (~9 min with Bedrock seed tests)
uv run pytest -m "not acceptance" -k "not TestSeedResolutionExpectations"   # quick (~30s)
uv run pytest tests/test_resolve.py              # resolution scenarios only
```

Tests requiring Neo4j or Bedrock skip cleanly when those aren't reachable. The curated CSV doubles as the acceptance fixture (FR-25) — every planted scenario has a test asserting its expected outcome.

## Repository layout

```
trace-poc/
├── api/                   # FastAPI modular monolith (five modules + graph/config/seeding)
├── ui/                    # React SPA (Vite + TypeScript + react-force-graph)
├── config/settings.yaml   # single externalized settings file (NFR-6)
├── spec/                  # requirements specification
├── docs/
│   ├── contracts/         # versioned boundary contracts + JSON Schemas
│   └── test-data/         # seed CSVs, negative fixtures, generator
├── scripts/               # contract schema generator
└── tests/                 # pytest suite incl. §8 acceptance walkthrough
```

## Contributing

Contributions are welcome. Please read [CONTRIBUTING.md](CONTRIBUTING.md) before opening a pull request. The spec is the source of truth — changes to behavior should start there or align with it. Known deviations from the spec's letter (Neo4j 2026.x instead of 5.x, Bedrock instead of a local embedder, the name-equality bar on Tier-3 auto-match) are recorded with rationale in [CLAUDE.md](CLAUDE.md).

## Security

Report vulnerabilities privately — see [SECURITY.md](SECURITY.md).

## License

Licensed under the [Apache License, Version 2.0](LICENSE).
