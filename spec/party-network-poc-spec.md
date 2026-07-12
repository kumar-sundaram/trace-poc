# Party Network Platform — POC Requirements Specification

**Status:** Draft baseline for review · working name pending
**Intended use:** Implementation-ready spec for a spec-driven build (harness-neutral)
**Scope owner:** Lead Architect, P&S

---

## 1. Purpose

Validate the core mechanics of a graph-based party network platform: party identity resolution as a baseline capability, with relationship traversal and pattern-based signal detection as the differentiated capabilities layered on top.

The graph is maintained transactionally: multiple upstream systems each manage their own party-to-loan relationships, and each relevant transaction in those systems produces an ingestion event that updates the graph. No single upstream system holds the combined picture — the party–property–loan graph **is** the big picture, consolidated across all of them. Upstream systems remain the systems of record for their own domains; the graph is the only place the cross-system network exists.

This is a feasibility build. It deliberately excludes production scale, security hardening, and live integration with any real upstream or downstream system.

## 2. Goals

- G1: Demonstrate tiered party resolution (deterministic → vector → LLM disambiguation) writing to a single knowledge graph, for both individuals and business entities.
- G2: Demonstrate read-only exposure lookup — all properties, loans, and related parties connected to a given party within a bounded traversal, across every role that party plays.
- G3: Demonstrate at least one pattern rule evaluating graph state and emitting a structured signal event.
- G4: Demonstrate transactional, multi-source ingestion: events from more than one simulated upstream system converging on the same graph, idempotently.
- G5: Demonstrate all capabilities through a minimal web UI suitable for a stakeholder demo.
- G6: Keep the entire system runnable on a laptop with two processes (app + database).

## 3. Non-goals (explicitly out of scope)

- Production deployment, clustering, HA, or performance testing at scale
- Authentication, authorization, or policy-based access control
- Live integration with any real upstream or downstream system (upstream systems are simulated by tagged ingestion events; outcome and signal events are published to file-based streams in the defined contract shapes only)
- Graph Data Science / batch algorithms (community detection, centrality)
- Data migration from, or comparison against, any existing mastering system
- Relationship lifecycle beyond create (role end-dating, party merge/split/retire, corrections from upstream)
- UI polish beyond demo-grade

## 4. Party model

### 4.1 Party types

Every party is either an **Individual** (first name + last name) or a **Business Entity** (LLC/firm name). Both carry an address and an optional SSN (individuals) or Tax ID (entities).

**Address requirement:** address is **required** for any party submitted in the `BORROWER` role — name + address is the minimum resolution basis for borrowers, and the pipeline must never receive a borrower without it. For other roles, address is strongly expected but not rejected when absent; resolution for address-less parties falls back to name-only matching at reduced confidence, and the response must reflect that reduced confidence.

All capabilities must function when SSN/Tax ID is absent.

**Identifier protection (production constraint, POC exemption):** the POC uses synthetic identifiers in plain form. In production, SSN/Tax ID is tokenized before ingestion and the graph stores only tokens — raw identifiers never enter the system. The tokenization scheme must be **deterministic** (same input always yields the same token), otherwise Tier 1 equality matching breaks; format-preserving encryption satisfies this. Scheme selection and key management are out of POC scope but tracked (§10).

### 4.2 Party roles and upstream sources

A party's role is a property of its relationship to a loan, **not** an attribute of the party itself. The same person or entity may be a Borrower on one loan, a Key Borrower Principal on another, and a Sponsor on a third — and must resolve to a single Party node across all of them. Cross-role exposure aggregation is a core capability, not an edge case.

**Roles in POC scope:** `BORROWER` (primary focus), `KEY_BORROWER_PRINCIPAL`, `SPONSOR`.

**Multi-source reality:** different role relationships are managed by different upstream transactional systems — borrower/principal/sponsor relationships originate from loan-submission systems, while third-party roles (e.g., engineering firm, property management firm, investor) are managed in their own upstream systems. The graph consolidates all of them. Consequently:

- The role vocabulary must be configuration-driven, not hard-coded, so new role types onboard without schema or code changes.
- Every ingestion event carries a `sourceSystem` identifier; the graph records provenance so any edge can be traced to the system and event that produced it.
- The ingestion contract must not assume any single upstream schema; the POC simulates at least two distinct source systems.

## 5. System shape

One FastAPI backend with internal module boundaries, a React single-page UI, and a local Neo4j Community Edition instance. Module boundaries are drawn where future service boundaries would fall.

```
api (Python / FastAPI, single deployable)
├── ingestion/    — receives tagged party events, validates (Pydantic), normalizes
├── resolve/      — tiered matching pipeline, transactional graph writes
├── explore/      — read-only traversal queries
├── signal/       — pattern rule evaluation post-write
└── emitter/      — publishes outcome and signal events to the outbound contracts
ui (React SPA, built statically and served by the api container in the POC)
neo4j (Community Edition, local instance, no plugins)
```

**Flow:** upstream system calls the resolution API → payload validated (contract violations rejected synchronously with `4xx`) → accepted with `202` + correlation reference → resolve → transactional graph write → signal evaluation (post-write hook) → emitter publishes outcomes as events: a **resolution-outcome event** for data consumers (e.g., the originating transactional system enriching its records with the mastered party), and — when a rule fires — a **signal event** for risk consumers. Explore is an independent synchronous read path; it never writes and never triggers rules.

### 5.1 Prioritized architectural characteristics

Explicitly ranked. When requirements conflict, higher wins. Just as important: the characteristics deliberately traded away, so nobody optimizes for them by accident.

| Rank | Characteristic | What it means here | Enforced by |
|---|---|---|---|
| 1 | Auditability / traceability | Every node, edge, match decision, and signal traces to the upstream event and method that produced it | FR-7, FR-11 (provenance), FR-19 (evidence path) |
| 2 | Extensibility | New role types, source systems, matching tiers, and pattern rules onboard via configuration or a new implementation of an existing interface — never a schema or core-code change | §4.2, FR-11, NFR-6 |
| 3 | Data integrity | Resolution writes are all-or-nothing; duplicate delivery is absorbed; low-confidence matches can never silently merge parties | FR-2 (idempotency), FR-5 (confidence cap), NFR-2 (single ACID transaction) |
| 4 | Testability | Every external dependency (LLM, embeddings) sits behind an interface with a deterministic local implementation; the seed dataset doubles as the acceptance fixture | FR-6, NFR-3, FR-25 |
| 5 | Simplicity / deployability | Two local processes, single-command startup each, runnable on a laptop | G6, NFR-4 |

**Deliberately traded away in the POC:** scalability, availability/fault-tolerance, security (authn/authz), and operability (observability beyond logs). These are v1 concerns; designing for them now would slow validation without changing the answer the POC exists to produce. Two forward concessions: the degree guard (FR-14) is kept in scope because real-world data pathology (supernodes) would invalidate the feasibility result itself, and the scale probe (NFR-7) answers the stated production volume (~100k parties) as a one-time measurement rather than an engineering effort.

### 5.2 Architecture patterns

- **Modular monolith.** One deployable, five modules, boundaries drawn where future service boundaries would fall (ingestion, resolve, explore, signal, emitter). The POC proves the seams; v1 splits along them without refactoring.
- **Pipeline (chain of responsibility) for Resolve.** Matching tiers execute as an ordered chain — deterministic → vector → LLM disambiguation — where each stage either resolves or defers to the next. Adding a tier is inserting a stage, not rewriting the pipeline.
- **Ports and adapters.** The LLM client, embedding client, and signal emitter are ports; the POC binds mock/local/log adapters, production binds hosted-model and downstream-system adapters. The core never knows the difference (FR-6, NFR-3, FR-20).
- **Read/write path separation (CQRS-lite).** Explore is a strictly read-only path with its own query model concerns (degree guard, flag references); ingestion→resolve→signal is the write path. They share the graph, not code paths (FR-16).
- **Event-carried state transfer, simulated.** Ingestion events carry everything the graph needs (sourceSystem, eventId, full party payload); the graph never calls back to upstream systems. This is what makes the consolidated-picture claim in §1 architecturally true rather than aspirational.
- **Published contract at every boundary.** The ingestion request schema and both outbound event schemas (resolution-outcome, signal) are versioned, documented deliverables (§9) — the system's edges are contracts, not implementation details.

### 5.3 Governing principles

1. **The graph is the consolidated picture, not the system of record.** Upstream systems own their domains; the graph owns the cross-system network view. No capability may be designed that requires the graph to be authoritative over an upstream system's data.
2. **No untraced edges.** If a relationship cannot be attributed to a source event and a match method, it does not get written.
3. **Confidence is explicit, everywhere.** Every match and every edge carries its tier and score. Nothing downstream is allowed to treat a T4 shared-attribute edge like a T1 deterministic one.
4. **Signals advise, humans decide.** A signal is an advisory artifact routed to review — never an automated decision, never a gate on any upstream transaction. This principle survives into production unchanged.
5. **Fail toward review, not toward merge.** When matching is uncertain, the system creates a new party or defers to disambiguation; it never silently merges. A duplicate party is a recoverable error; a wrong merge is a contaminated one.
6. **Configuration over code for everything tunable.** Thresholds, windows, vocabularies, and source systems live in config (NFR-6); changing behavior must not require redeployment logic changes.
7. **The POC's honesty is a feature.** Non-goals (§3) are commitments, not apologies — anything that quietly exceeds them (background hardening, speculative scale work) is scope creep even if it's good engineering.

## 6. Functional requirements

### 6.1 Ingestion and Resolve — party identity resolution

- FR-1: Accept a party event via REST containing: `sourceSystem` (required); `eventId` (required, unique per source event, used for idempotency); `partyType` (INDIVIDUAL | ENTITY, required); for individuals `firstName` + `lastName` (required), for entities `entityName` (required); `address` (required when `role` = BORROWER, otherwise optional); `ssnOrTaxId` (optional); `role` (from the configured role vocabulary, optional); `loanRef` (required when `role` is present).
- FR-2: Ingestion is idempotent: re-delivery of an event with an already-processed (`sourceSystem`, `eventId`) pair must not create duplicate nodes, edges, or signals.
- FR-3: Tier 1 — deterministic match on exact SSN/Tax ID when present (on tokens in production; see §4.1).
- FR-4: Tier 2 — deterministic match on normalized name + normalized address. Normalization is party-type-aware: individuals — uppercase, punctuation-stripped, whitespace-collapsed full name; entities — the same plus legal-suffix normalization (LLC / L.L.C. / Limited Liability Company → LLC; Inc / Incorporated → INC; etc.). USPS-style street-type normalization is a stretch goal.
- FR-5: Tier 3 — vector similarity fallback when no deterministic match: embed the normalized name + address string, query a Neo4j native vector index over existing Party embeddings **of the same party type**, and treat results above a configurable similarity threshold as candidate matches. Individuals never match to entities and vice versa. For address-less parties (non-borrower roles), embedding uses name only and the resulting match confidence is capped below the auto-match band.
- FR-6: Tier 4 disambiguation — when Tier 3 returns candidates in an ambiguous band (two configurable thresholds: auto-match above, no-match below, disambiguate between), call an LLM with both records and receive a match/no-match/uncertain judgment. The LLM client must be an interface with a deterministic mock implementation so the POC runs without external credentials.
- FR-7: Every resolution decision writes, in a single transaction: the mastered Party node (created or matched), a RESOLVES_TO edge from the raw record, and match metadata (tier, method, confidence score, sourceSystem, eventId, timestamp). No raw record is ever discarded; alias history is preserved.
- FR-8: The ingestion API acknowledges an accepted event with HTTP `202` and a correlation reference (echoing `sourceSystem` + `eventId`). Contract violations (e.g., a borrower without an address) are rejected synchronously with `4xx` and no partial processing. Resolution outcomes are **not** returned in the response — they are published as events per FR-20.
- FR-9: When the event carries a `role` + `loanRef`, resolution additionally writes the role relationship per FR-12 in the same transaction. A repeat submission of the same party with a different role on a different loan — including from a **different** source system — must attach the new role edge to the existing Party node, not create a duplicate party.

### 6.2 Graph model

- FR-10: Node labels: `Party`, `Property`, `Loan`, `RawRecord`, `Signal`. Uniqueness constraints on each label's `id`. Indexes on `Party.normalizedName` and `Property.normalizedAddress`. `Party` carries `partyType`.
- FR-11: Relationship types: `RESOLVES_TO` (RawRecord→Party), `CONNECTED_TO` (Party→Property), `HAS_ROLE_ON` (Party→Loan). Every `CONNECTED_TO` and `HAS_ROLE_ON` edge carries `tier` (T1–T4), `source`, `sourceSystem`, and `eventId` properties; `HAS_ROLE_ON` additionally carries `role` (from the configured vocabulary). No untraced edges — every edge is attributable to the upstream event that produced it. A single relationship type with a role property — rather than one relationship type per role — is a deliberate choice for role extensibility (§4.2); revisit only if traversal performance data ever demands it.
- FR-12: Shared-attribute relationships (e.g., two parties sharing an address) are represented as each party connecting to the same attribute node with `source: 'shared_attribute'`, tier T4 — not as party-to-party edges.

### 6.3 Explore — exposure lookup

- FR-13: REST endpoint: given an **anchor node** — a party (by ID or name), a loan (by loanRef), or a property (by normalized address) — return all connected entities within 2 hops via `CONNECTED_TO`/`HAS_ROLE_ON`, including the path, edge tiers, roles, source systems, and node types. Party-anchored results must aggregate across all roles the party plays — a party who is Borrower on one loan and Sponsor on another returns both, with roles distinguishable in the response. A loan-anchored query returns the loan-scoped party graph (all parties and their roles on that loan) as an out-of-the-box operation.
- FR-14: Degree guard — before expanding through any node, check its relationship count; above a configurable threshold (default 200), do not expand: return a summary marker instead (`{node, degree, expanded: false}`).
- FR-15: If any party in the result set has an active signal against it (see 6.4), the response includes a flag reference (signal ID and pattern type only — no additional detail through this endpoint).
- FR-16: Explore performs no writes and triggers no rule evaluation.

### 6.4 Signal — pattern rule evaluation

- FR-17: One rule in POC scope, "attribute fan-out": N or more distinct parties (default 3) connected to the same attribute node via `shared_attribute` edges, whose loans (via any role) originated within a configurable window (default 14 days).
- FR-18: Rules run as a post-write hook after each resolution and are also invokable on demand via an admin endpoint (re-run against full graph).
- FR-19: A fired rule creates a `Signal` node in the graph (pattern type, related party IDs, evidence path, severity, status `RAISED`, timestamp) and passes it to the emitter.
- FR-20: The emitter publishes outbound events using a single shared envelope (eventType, schema version, correlation fields — `sourceSystem`, `eventId` — and timestamp) with type-specific payloads, to two dedicated streams (append-only JSONL files in the POC, each standing in for a broker topic): (a) **resolution-outcome** — mastered party ID, match tier, confidence, alias linkage; intended for upstream/data consumers. (b) **signal** — pattern type, related party IDs, evidence path, severity, plus a **causation reference** (the `eventId` of the ingestion event whose processing raised it), so consumers of both streams can reconstruct ordering across them; intended for risk consumers. This remains standard pub-sub — subscribers select by subscribing to the stream they need. Streams are separated by data classification, not convenience: subscribing to a stream is an infrastructural access decision, whereas filtering within a mixed stream would deliver risk-classified payloads to consumers that merely promise to discard them. Envelope and both payload schemas are deliverables.
- FR-21: The degree guard (FR-14) applies to rule evaluation: attribute nodes above the threshold are excluded from fan-out matching and logged as excluded-common-attribute.

### 6.5 UI

- FR-22: React single-page UI invoking the FastAPI endpoints. Three regions: (a) party search box invoking Explore, (b) rendered graph of the result (a React-compatible graph library, e.g., react-force-graph or Cytoscape.js via its React wrapper), (c) signals panel listing raised signals with related parties and pattern type.
- FR-23: Clicking a node in the rendered graph shows its properties, including party type and match tier for parties, and role + source system labels on loan edges.
- FR-24: A demo-reset control (admin endpoint + button) that clears the graph and reloads the synthetic dataset.

### 6.6 Synthetic dataset

- FR-25: A seed script loads 50–100 synthetic parties (a mix of individuals and business entities) attributed across **at least two simulated source systems**, including, at minimum: (a) one cluster of 3+ raw name variants that must resolve to one party via Tier 2; (b) one pair resolvable only via Tier 3/4 (fuzzy variant with a differing address); (c) one entity pair differing only by legal-suffix form (e.g., "Meridian Holdings LLC" vs "Meridian Holdings, L.L.C.") that must resolve via Tier 2 entity normalization; (d) one party holding different roles across multiple loans **arriving from two different source systems** (e.g., Borrower via the loan-submission source, engineering-adjacent Sponsor role via a second source) that must resolve to a single node with aggregated exposure; (e) one legitimate high-connectivity party (multiple properties/loans, long time spread) that must NOT fire the fan-out rule; (f) one planted fan-out pattern that MUST fire it; (g) one high-degree common attribute (e.g., an address shared by 250+ parties) that must be excluded by the degree guard; (h) one duplicated event (same sourceSystem + eventId delivered twice) that must be absorbed idempotently.
- FR-26: All data is synthetic. No real names, addresses, or identifiers.

## 7. Non-functional requirements

- NFR-1: Backend — Python 3.12+, FastAPI, Pydantic v2 for all request/response contracts, official Neo4j Python driver (no OGM required). UI — React 18+, TypeScript, built statically; no server-side rendering.
- NFR-2: Neo4j Community Edition 5.x, standard Cypher only — no APOC, no GDS, no Enterprise features. All multi-write resolutions execute in a single ACID transaction.
- NFR-3: Embedding client behind an interface (abstract base class) with a local deterministic implementation as default — e.g., sentence-transformers MiniLM if the dependency footprint is acceptable, otherwise a hash-based stand-in; a hosted-embedding implementation may be stubbed but must not be required to run.
- NFR-4: Runs entirely locally on a laptop: a local Neo4j Community Edition instance plus the FastAPI app, each started with a single command; `README` documents setup, run, and the demo script.
- NFR-5: Explore p50 under 500ms against the seeded dataset on a laptop (informal check, not a benchmark).
- NFR-6: Config (thresholds, windows, degree guard, role vocabulary, known source systems) externalized to a single settings file (pydantic-settings over `.env`/YAML); nothing tunable lives in code.
- NFR-7 (scale probe, stretch): a generator bulk-loads ~100k synthetic parties with ~1M relationships (separate from the curated seed set); after load, the NFR-5 Explore latency check must still hold and a full-graph Signal re-run (FR-18) must complete in under a few minutes on a laptop. This is a feasibility probe at the stated production party volume, not scale engineering.

## 8. Acceptance walkthrough (demo script)

1. Start the local Neo4j instance and the app → both healthy; seed data loaded.
2. Submit "Jon A. Smith" borrower variant (with address) via ingestion endpoint → `202` ack with correlation reference; the resolution-outcome event shows a Tier 2/3 match with confidence.
3. Submit a borrower event **without** an address → rejected with a clear validation error.
4. Submit the same individual as `SPONSOR` on a different loan from a **different sourceSystem** → `202` ack; the resolution-outcome event carries the **same party ID**; UI shows one node with two role edges, each labeled with its source system.
5. Re-deliver the exact same event (same sourceSystem + eventId) → no duplicate edges; idempotency confirmed.
6. UI search for the legitimate high-connectivity party → graph renders full exposure across roles; no signal shown.
7. UI search for a party in the planted fan-out cluster → graph renders shared attribute; signals panel shows the raised signal; Explore response carries the flag reference.
8. Search touching the high-degree common attribute → returns summary marker, not thousands of paths; excluded-attribute log entry present.
9. Inspect both event streams → resolution-outcome and signal events match their documented contract schemas, and every outcome event correlates back to its originating request.

## 9. Deliverables

- Running system per NFR-4
- Ingestion request contract (documented, source-system-tagged)
- Outbound event contracts: resolution-outcome and signal (versioned JSON, documented)
- Seed dataset + reset capability
- README with demo script above

## 10. Open items (tracked, not blocking)

- Product name — tabled
- Vector index dimension/model choice — decided at build time based on default embedding implementation
- Tier 3/4 threshold defaults — initial values set at build time, tuned during demo prep
- Role vocabulary governance (who approves new role types) — post-POC concern
- Relationship lifecycle semantics (role end-dating, upstream corrections/retractions) — post-POC; the provenance fields (sourceSystem, eventId) are the hook that makes this addable later
- Event delivery guarantees (transactional outbox after graph commit, at-least-once delivery, idempotent consumers) and broker selection — post-POC; the file-based streams stand in for real topics
- SSN/Tax ID tokenization scheme and key management — post-POC; must be deterministic to preserve Tier 1 equality matching (§4.1)
- Target-state architecture (decision recorded, revised): a **single party-intelligence platform on one graph database**, co-locating identity lineage (golden parties, issued IDs, raw records, aliases, match decisions) with the relationship network (exposure, signals). Rationale: (a) resolution lineage is itself a graph — golden → issued IDs → aliases with provenance is one traversal, not a cross-store join; (b) co-location enables **context-aware resolution** — matching informed by network evidence (shared attributes, hierarchy, alias variance) — which is the primary lever against match-accuracy/manual-review pain; (c) alias variance is itself an analytical signal, only queryable when lineage and network share a store. The versioned resolution-outcome contract remains the sole external integration seam regardless. **Migration mode:** phase 1 ingests the current mastering system's outcomes (skeleton fidelity) so graph analytics ships independently; phase 2 absorbs modernized mastering into the platform behind the unchanged contract. **Accepted costs:** mixed data classification in one store pushes access enforcement to the service layer or to Neo4j Enterprise/Aura (fine-grained security is not in Community Edition); single-platform blast radius is mitigated by module boundaries and the published contract.
- Golden ID permanence and survivorship (decision recorded): a mastered ID issued to a transactional system is **permanent** — upstream systems never re-point after a merge. All survivorship bookkeeping (issued ID → canonical identity) lives inside the mastering system, and lookups anchored on any issued ID resolve through it transparently. Merge/equivalence events still exist on the stream, but the contract distinguishes two consumer classes: **reference holders** (transactional systems) may ignore them; **state materializers** (the graph projection) must consume them, representing equivalence non-destructively (a SAME_AS edge between party nodes rather than a destructive node merge) so exposure aggregates across merged identities while remaining auditable — and reversible if a merge proves wrong. This relocates the indirection the loan-scoped child-ID scheme provided into the mastering system, where identity bookkeeping belongs. Corollary: consumers never compare golden IDs across systems to establish identity; identity questions go to Explore.
- Explicit party-to-party relationship edges (ownership/control/principal, e.g., from borrower org-chart ingestion) — a model extension via a new relationship type in the configured vocabulary; post-POC.
