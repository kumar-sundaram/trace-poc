# Contributing

Thank you for your interest in the Party Network Platform POC. This project is spec-driven: [`spec/party-network-poc-spec.md`](spec/party-network-poc-spec.md) is the source of truth for requirements and acceptance behavior.

## Before you start

1. Read the spec, especially sections 3 (non-goals), 5 (architecture), and 8 (acceptance walkthrough).
2. Review [`CLAUDE.md`](CLAUDE.md) for implementation conventions and non-negotiable rules.
3. Check open issues and pull requests to avoid duplicate work.

## How to contribute

### Reporting bugs

Open a [bug report](.github/ISSUE_TEMPLATE/bug_report.md) with:

- Steps to reproduce
- Expected vs. actual behavior
- Relevant spec requirement IDs (e.g., FR-2, NFR-4) when applicable

### Suggesting enhancements

Open a [feature request](.github/ISSUE_TEMPLATE/feature_request.md). For spec-level changes, describe the requirement change and acceptance impact before implementation.

### Pull requests

1. Fork the repository and create a branch from `main`.
2. Keep changes focused — one logical change per PR when possible.
3. Align implementation with the spec. If the spec needs to change, update it in the same PR and explain why.
4. Preserve planted acceptance scenarios in [`docs/test-data/party_network_seed_curated.csv`](docs/test-data/party_network_seed_curated.csv) unless the spec explicitly changes them.
5. Do not commit secrets (`.env`, API keys, credentials).
6. Fill out the pull request template completely.

### Spec changes

When modifying the spec:

- State whether the change is clarifying (no behavior change) or behavioral.
- Update related test-data documentation if acceptance scenarios shift.
- Keep non-goals explicit — scope creep (auth, HA, production hardening) belongs in tracked open items, not in the POC.

## Development conventions

- **Auditability first** — every graph write must carry provenance.
- **Fail toward review, not merge** — uncertain matches must not silently merge parties.
- **Configuration over code** — tunable thresholds and vocabularies belong in settings, not hard-coded.
- **Ports and adapters** — external dependencies (LLM, embeddings, emitter) behind interfaces with local defaults.
- **Synthetic data only** — never add real PII to fixtures or examples.

## Code style

Follow existing patterns in the codebase. When application code lands:

- Python: type hints, Pydantic v2 for contracts, FastAPI conventions
- TypeScript/React: match established UI structure and lint rules
- Cypher: standard Neo4j Community Edition only — no APOC, GDS, or Enterprise features

## Questions

Open a [question issue](.github/ISSUE_TEMPLATE/question.md) for design or spec interpretation questions.

## Code of conduct

This project follows the [Contributor Covenant Code of Conduct](CODE_OF_CONDUCT.md). By participating, you agree to uphold it.
