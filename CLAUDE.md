# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository state

This repo is a spec-driven POC build. **The spec is the source of truth** — read `spec/party-network-poc-spec.md` before implementing anything. All requirement references below (FR-x, NFR-x, G-x, §x) point into that file. Synthetic test data lives under `docs/test-data/`; regenerate with `python docs/test-data/generate_parties.py`.

## Commands

- `make db` / `make db-stop` — start/stop the brew-installed Neo4j (`neo4j start`)
- `make run` — start the FastAPI app (`uv run uvicorn api.main:app --reload`)
- `make seed` — full demo reset from the CLI (`uv run python -m api.seeding`): wipe graph + streams, reload the curated CSV through the real ingestion path. Same operation as `POST /admin/reset`. Takes ~2–4 min on Bedrock embeddings (273 events); use `TRACE_EMBEDDING__ADAPTER=hash` for a fast structural load.
- `make test` — run the pytest suite (`uv run pytest`; single test: `uv run pytest tests/test_config.py::test_env_override`). The full suite includes two Bedrock full-seed runs (~4 min each: the seed-expectations class and the §8 acceptance walkthrough). Quick iteration: `uv run pytest -m "not acceptance" -k "not TestSeedResolutionExpectations"` (~30s).
- `make ui` — build the SPA (`cd ui && npm install && npm run build`); FastAPI serves `ui/dist` at `/` when present. Dev mode: `cd ui && npm run dev` (Vite proxy to :8000).
- `make lint` — `uv run ruff check .`
- `uv sync` — install/refresh dependencies (dev group included by default)

Settings live in `config/settings.yaml` (NFR-6), overridable via `TRACE_*` env vars with `__` as the nesting delimiter (e.g. `TRACE_SIGNAL__FANOUT_MIN_PARTIES=5`).

**Shared-database warning:** tests, the demo app, and the seeder all use the one local Neo4j. Tests wipe the graph (`clean_graph`), so run `make seed` after a test run to restore the demo dataset — and never run tests concurrently with seeding: they clobber each other's graph state AND the parallel Bedrock calls trip `ThrottlingException` (observed 2026-07-12).

## What is being built

A POC of a graph-based party network platform: tiered party identity resolution (deterministic → vector → LLM disambiguation) writing to a single Neo4j knowledge graph, plus read-only exposure traversal and pattern-based signal detection. Multiple simulated upstream systems feed the graph via ingestion events; the graph is the only place the consolidated cross-system party–property–loan network exists.

## Mandated stack (NFR-1, NFR-2)

- Backend: Python 3.12+, FastAPI, Pydantic v2 for all contracts, official Neo4j Python driver (no OGM)
- Graph: Neo4j Community Edition 5.x, standard Cypher only — **no APOC, no GDS, no Enterprise features**
- UI: React 18+ with TypeScript, built statically and served by the API; no SSR
- Runs as exactly two local processes (app + Neo4j), each started with a single command (G6, NFR-4)

## Architecture (§5)

Modular monolith — one FastAPI deployable with five modules whose boundaries are future service seams:

```
api
├── ingestion/  — receives tagged party events, validates (Pydantic), normalizes
├── resolve/    — tiered matching pipeline, transactional graph writes
├── explore/    — read-only traversal queries
├── signal/     — pattern rule evaluation post-write
└── emitter/    — publishes resolution-outcome and signal events (JSONL streams in POC)
```

Key patterns to preserve:
- **Resolve is a chain of responsibility**: Tier 1 (exact SSN/Tax ID) → Tier 2 (normalized name+address) → Tier 3 (vector similarity, same party type only) → Tier 4 (LLM disambiguation). Adding a tier = inserting a stage.
- **Ports and adapters**: the LLM client, embedding client, and emitter are interfaces (abstract base classes) with deterministic local/mock defaults — the POC must run with no external credentials (FR-6, NFR-3).
- **Read/write separation**: Explore never writes and never triggers rules (FR-16); ingestion→resolve→signal is the write path.
- **Published contracts at every boundary**: the ingestion request schema and both outbound event schemas (resolution-outcome, signal) are versioned deliverables, not implementation details.

Write flow: REST event → validate (contract violations rejected `4xx` synchronously) → `202` + correlation reference → resolve → single ACID transaction writing Party/RESOLVES_TO/role edges + match metadata → signal rule evaluation (post-write hook) → emitter publishes events. Resolution outcomes are never returned in the HTTP response — only on the event stream (FR-8, FR-20).

## Graph model (FR-10 to FR-12)

Nodes: `Party`, `Property`, `Loan`, `RawRecord`, `Signal`. Edges: `RESOLVES_TO` (RawRecord→Party), `CONNECTED_TO` (Party→Property), `HAS_ROLE_ON` (Party→Loan, carries `role` property — one relationship type with a role property, deliberately, for role extensibility). Every edge carries `tier`, `source`, `sourceSystem`, `eventId`. Shared attributes (e.g., common address) are attribute nodes each party connects to, never party-to-party edges.

## Non-negotiable rules

Ranked characteristics when requirements conflict (§5.1): auditability > extensibility > data integrity > testability > simplicity. Scalability, HA, authn/authz, and observability are deliberately out of scope — building them is scope creep (§3, principle 7).

- **No untraced edges**: every node/edge/decision must carry provenance (sourceSystem, eventId, tier, method).
- **Idempotency**: re-delivery of the same (`sourceSystem`, `eventId`) must not create duplicate nodes, edges, or signals (FR-2).
- **Fail toward review, not merge**: uncertain matches create a new party or defer to disambiguation — never silently merge. Address-less non-borrower parties get confidence capped below the auto-match band (FR-5).
- **Borrower events require an address**; rejected `4xx` otherwise. Other roles accept missing address at reduced, explicitly reported confidence (§4.1).
- **Configuration over code**: thresholds, disambiguation bands, degree guard, time windows, role vocabulary, and known source systems live in a single pydantic-settings config (NFR-6) — nothing tunable in code. Role vocabulary especially must be config-driven (§4.2).
- **Degree guard**: nodes above a configurable relationship-count threshold (default 200) are not expanded in Explore and are excluded from signal fan-out matching (FR-14, FR-21).
- **Signals advise, humans decide**: a signal is advisory, never an automated decision or gate.

## Build decisions (agreed 2026-07-12)

- Tier 3 embeddings: Amazon Bedrock Titan Embed v2 (`amazon.titan-embed-text-v2:0`, 512-dim, us-east-1) as the default adapter (decided 2026-07-12, superseding the earlier MiniLM choice — user preferred Bedrock over a local PyTorch dependency). A deterministic hash-based local adapter (`TRACE_EMBEDDING__ADAPTER=hash`) is the credential-less fallback required by NFR-3, also preferred for CI and the 100k scale probe. Vector index dimension follows config; `bootstrap_schema` drops/recreates the index on dimension drift.
- Tier 4 mock LLM: name-equality heuristic (equal/near-equal normalized names despite differing addresses → match, else uncertain → new party). This is what makes the HIGH_CONNECTIVITY_NEGATIVE rows (same name, six different addresses) resolve to one party.
- Fan-out window (FR-17): ingestion processing timestamps stand in for loan origination dates — the test CSVs carry no date column. `Loan.originatedAt` is set on first MERGE.
- T3 auto-match requires exact normalizedName equality on top of the score threshold (decided 2026-07-12): the 250 `Generic Holdings {N} LLC` seed entities at one address embed near-identically (~0.99), so score alone would silently merge them. Differing names always go to Tier 4. The mock LLM additionally treats names with differing numeric tokens as distinct registrations (NO_MATCH).
- T3 thresholds are in Neo4j vector score space, (1+cosine)/2 — calibrated against measured Titan scores (see comments in `config/settings.yaml`).
- Resolve tests (`tests/test_resolve.py`) run against real Bedrock (skipped without credentials) because thresholds are Titan-calibrated; ingestion tests run on the hash adapter.
- Signal identity is one per (patternType, attributeId) — a growing cluster is one reviewable fact, so parties joining an already-raised pattern don't re-fire it. When the degree guard trips on an attribute, signals raised earlier (while it was legitimately below threshold) are reclassified to status `EXCLUDED_DEGREE_GUARD`, never deleted; `GET /signals` returns only `RAISED` (decided 2026-07-12 — incremental loading of the 250-party seed address otherwise produced 198 duplicate signals).
- Role vocabulary config additionally includes `GUARANTOR` and `PROPERTY_MANAGER` (present in the test data).
- Neo4j runs natively via Homebrew (`brew install neo4j`), not Docker — Docker Desktop is not installed on the dev machine (decided 2026-07-12, superseding the earlier Docker choice). Installed version is 2026.06.0 Community (brew no longer offers 5.x; a known, accepted deviation from NFR-2's literal "5.x" — Community edition, standard Cypher, and native vector indexes all verified present). Credentials `neo4j`/`trace-poc-dev` per `config/settings.yaml`.
- Python tooling is `uv`; UI is Vite + React 18 + TS with react-force-graph; tests are pytest with the CSVs as fixtures.
- In scope beyond core: NFR-7 scale probe, USPS street-type normalization, hosted-adapter stubs.
- NFR-7 probe (run 2026-07-12, results in `docs/scale-probe-results.md`): uses local MiniLM via the opt-in `scale` dependency group (`uv sync --group scale`, adapter `minilm`, 384-dim) — chosen over Bedrock for the 100k bulk load (cost was trivial, ~$0.05–0.30; sequential call time of 1.5–3h was the blocker). `scripts/scale_probe.py` wipes the graph, bulk-loads with amplified role edges to reach ~1M relationships, and measures Explore p50 + full-graph signal re-run. Run `make seed` afterwards to restore the demo graph and the 512-dim Titan index.

## Seed dataset and acceptance

The synthetic seed dataset (FR-25, 50–100 parties across ≥2 simulated source systems) doubles as the acceptance fixture — see `docs/test-data/party_network_seed_curated.csv`. It must contain specific planted cases (Tier 2 variant cluster, Tier 3/4 fuzzy pair, legal-suffix entity pair, cross-source multi-role party, legitimate high-connectivity party that must NOT fire the fan-out rule, planted fan-out that MUST, a degree-guard-excluded common attribute, a duplicated event). The demo script in §8 is the acceptance walkthrough; changes should keep it passing end to end. All data is synthetic (FR-26).
