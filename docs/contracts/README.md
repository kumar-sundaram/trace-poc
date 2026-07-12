# Boundary contracts

## Ingestion request (FR-1)

`POST /events` accepts one source-tagged party event
([`ingestion-request.schema.json`](ingestion-request.schema.json)):

- `sourceSystem` (required, must be a configured known source system), `eventId`
  (required, unique per source event — the `(sourceSystem, eventId)` pair is the
  idempotency key, FR-2)
- `partyType` — `INDIVIDUAL` (requires `firstName` + `lastName`) or `ENTITY`
  (requires `entityName`)
- `address` — **required when `role` = `BORROWER`** (§4.1), otherwise optional
  (resolution falls back to name-only at reduced, capped confidence)
- `ssnOrTaxId` — optional (plain synthetic values in the POC; tokens in production)
- `role` — optional, from the configured role vocabulary; `loanRef` required
  when `role` is present

Contract violations are rejected synchronously with `422` and no partial
processing (FR-8). Accepted events return `202` with a correlation reference
only — resolution outcomes are published on the resolution-outcome stream,
never in the HTTP response.

# Outbound event contracts (FR-20)

Schema version: **1.0.0** (carried in every envelope as `schemaVersion`).

The system publishes to **two dedicated streams**, separated by data
classification — subscribing to a stream is an infrastructural access
decision, so risk-classified payloads never transit a stream that data
consumers read:

| Stream | POC file (stands in for a broker topic) | Consumer class |
|---|---|---|
| resolution-outcome | `data/streams/resolution-outcome.jsonl` | Upstream/data consumers enriching records with the mastered party |
| signal | `data/streams/signal.jsonl` | Risk consumers routing advisories to review |

Both streams carry the **shared envelope** with a type-specific `payload`.
The envelope's correlation fields (`sourceSystem`, `eventId`) always identify
the **originating ingestion event**, so consumers of both streams can
reconstruct cross-stream ordering. The signal payload additionally repeats
this as an explicit `causationEventId`.

## Envelope

- `eventType` — `resolution-outcome` | `signal`
- `schemaVersion` — semver of this contract
- `sourceSystem`, `eventId` — correlation to the ingestion event
- `timestamp` — ISO-8601 UTC, time of emission
- `payload` — see below

## resolution-outcome payload

- `masteredPartyId` — the golden party the raw record resolved to
- `created` — `true` if a new party was created, `false` if matched
- `matchTier` — `T1`–`T4`, `null` when a new party was created
- `matchMethod` — e.g. `exact_ssn`, `normalized_name_address`, `vector_similarity`, `llm_disambiguation`
- `confidence` — 0.0–1.0
- `rawRecordId`, `aliasName` — alias linkage (FR-7: no raw record is discarded)

## signal payload

- `signalId`, `patternType` (`attribute_fanout` in POC), `severity` (`LOW`|`MEDIUM`|`HIGH`)
- `relatedPartyIds` — parties implicated by the pattern
- `evidencePath` — ordered node/edge references substantiating the pattern (FR-19)
- `causationEventId` — eventId of the ingestion event whose processing raised it

## Machine-readable schemas

Generated from the Pydantic models (the single source of truth) by
`uv run python scripts/generate_contract_schemas.py`; a test keeps them in sync:

- [`event-envelope.schema.json`](event-envelope.schema.json)
- [`resolution-outcome-payload.schema.json`](resolution-outcome-payload.schema.json)
- [`signal-payload.schema.json`](signal-payload.schema.json)

## Delivery semantics (POC)

Append-only files, one JSON document per line, emitted after the graph
transaction commits. Real delivery guarantees (transactional outbox,
at-least-once, idempotent consumers) and broker selection are tracked
post-POC (spec §10).
