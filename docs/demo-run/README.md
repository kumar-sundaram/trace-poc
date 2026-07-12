# Demo run snapshot — 2026-07-12

Captured stream output from a live end-to-end §8 acceptance walkthrough
(seeded curated dataset + the walkthrough's live submissions), preserved as
evidence of the demonstrated behavior. Both files validate against the
[published contracts](../contracts/) at schema version 1.0.0.

| File | Events | Contents |
|---|---|---|
| `resolution-outcome.jsonl` | 275 | 273 seed events (274 rows, 1 duplicate absorbed) + the walkthrough's "Jon A. Smith" borrower variant (`live-demo-jon-1`, resolved T4/llm_disambiguation, confidence 0.8998) and cross-source SPONSOR (`live-demo-jon-2`, same mastered party) |
| `signal.jsonl` | 2 | The planted fan-out raise (777 Risk Ave, 3 parties, MEDIUM) and the seed-time raise on the registered-agent address — emitted when it legitimately fired at 3 parties, later reclassified `EXCLUDED_DEGREE_GUARD` in the graph (retraction events are post-POC scope) |

Reproduce the state: `make seed`, then run the demo script in the
[root README](../../README.md#demo-script-8). This snapshot is static; the
live streams are written to `data/streams/` (gitignored).
