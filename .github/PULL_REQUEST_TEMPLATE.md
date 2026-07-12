## Summary

<!-- What does this PR change and why? Link related issues with "Fixes #123" or "Relates to #456". -->

## Spec alignment

- [ ] Behavior matches [`spec/party-network-poc-spec.md`](spec/party-network-poc-spec.md) (or the spec is updated in this PR)
- [ ] Acceptance scenarios / planted test cases are preserved or intentionally updated with rationale
- [ ] No scope creep into spec non-goals (auth, HA, production hardening, etc.)

## Type of change

- [ ] Bug fix
- [ ] New feature / implementation
- [ ] Spec or documentation update
- [ ] Test data / fixture change
- [ ] Refactor (no behavior change)
- [ ] Chore (tooling, CI, dependencies)

## Test plan

<!-- How did you verify this? Commands run, manual demo steps, etc. -->

- [ ] Regenerated or validated test data (`python docs/test-data/generate_parties.py`) if fixtures changed
- [ ] Ran relevant tests (list commands when available)
- [ ] Walked acceptance steps from spec section 8 (when applicable)

## Checklist

- [ ] No secrets, real PII, or credentials committed
- [ ] Synthetic data only in fixtures and examples
- [ ] Follows ports-and-adapters / configuration-over-code conventions where applicable
