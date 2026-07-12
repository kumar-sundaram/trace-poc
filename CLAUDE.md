# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository state

This repo is a spec-driven POC build. **The spec is the source of truth** — read `spec/party-network-poc-spec.md` before implementing anything. All requirement references below (FR-x, NFR-x, G-x, §x) point into that file. Synthetic test data lives under `docs/test-data/`; regenerate with `python docs/test-data/generate_parties.py`. No application build/test tooling exists yet; when it is added, record the actual commands here.

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

## Seed dataset and acceptance

The synthetic seed dataset (FR-25, 50–100 parties across ≥2 simulated source systems) doubles as the acceptance fixture — see `docs/test-data/party_network_seed_curated.csv`. It must contain specific planted cases (Tier 2 variant cluster, Tier 3/4 fuzzy pair, legal-suffix entity pair, cross-source multi-role party, legitimate high-connectivity party that must NOT fire the fan-out rule, planted fan-out that MUST, a degree-guard-excluded common attribute, a duplicated event). The demo script in §8 is the acceptance walkthrough; changes should keep it passing end to end. All data is synthetic (FR-26).
