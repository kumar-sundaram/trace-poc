# Test data

Synthetic ingestion fixtures for TDD and acceptance testing. All data is fictional (FR-26).

## Files

| File | Records | Purpose |
|---|---|---|
| `party_network_seed_curated.csv` | 274 | FR-25 acceptance fixture — planted scenarios, not shuffled |
| `party_network_negative.csv` | 3 | Contract violations expected to return `4xx` |
| `party_network_scale_100k.csv` | 100,000 | NFR-7 scale probe — bulk synthetic background only |

## Regenerate

```bash
python docs/test-data/generate_parties.py
```

Requires `faker` (`pip install faker`). Output is written alongside this README.

## CSV schema

Columns match the ingestion contract (FR-1) plus a `scenario` tag for test filtering:

`scenario`, `sourceSystem`, `eventId`, `partyType`, `firstName`, `lastName`, `entityName`, `address`, `ssnOrTaxId`, `role`, `loanRef`

## Curated scenarios

| `scenario` | Spec reference | What it tests |
|---|---|---|
| `T2_VARIANT_CLUSTER` | FR-25a, §8 step 2 | Jonathan / JONATHAN / Jon A. Smith → one party |
| `IDEMPOTENCY_DUPLICATE` | FR-25h, §8 step 5 | Identical re-delivery absorbed |
| `T2_ENTITY_SUFFIX` | FR-25c | LLC vs L.L.C. entity normalization |
| `TIER1_SSN_MATCH` | FR-3 | Same SSN, different name spelling |
| `T3_T4_FUZZY` | FR-25b | Robert vs Robb Chen, different addresses |
| `HIGH_CONNECTIVITY_NEGATIVE` | FR-25e, §8 step 6 | Patricia Morrison — multi-loan exposure, no fan-out |
| `FANOUT_POSITIVE` | FR-25f, §8 step 7 | Three entities sharing one address → signal |
| `DEGREE_GUARD` | FR-25g, §8 step 8 | 250 parties at registered-agent address |
| `ADDRESS_LESS_CONFIDENCE` | FR-5, §4.1 | Sponsor without address — capped confidence |
| `PARTY_TYPE_ISOLATION` | FR-5 | Individual vs entity must not merge |
| `MULTI_SOURCE_ENTITY_EXPOSURE` | FR-25d (supplementary) | Same entity across source systems |

Jonathan Smith cluster rows also cover **FR-25d** (cross-source multi-role) and **§8 steps 4–5**.

## Negative scenarios

| `scenario` | Expected result |
|---|---|
| `VALIDATION_REJECT_BORROWER_NO_ADDRESS` | `4xx` — borrower requires address |
| `VALIDATION_REJECT_INDIVIDUAL_MISSING_NAME` | `4xx` — individual missing first/last name |
| `VALIDATION_REJECT_ENTITY_MISSING_NAME` | `4xx` — entity missing entityName |

## Usage in tests

```python
import csv
from pathlib import Path

data_dir = Path("docs/test-data")
with open(data_dir / "party_network_seed_curated.csv") as f:
    fanout = [r for r in csv.DictReader(f) if r["scenario"] == "FANOUT_POSITIVE"]
```

- **Resolve / signal / explore tests** → curated CSV
- **Validation tests** → negative CSV
- **Performance / NFR-7** → scale CSV (load separately from curated)

## Notes

- Fan-out timing (FR-17, 14-day window) depends on processing timestamps at runtime; load `FANOUT_POSITIVE` rows in a single batch for deterministic signal tests.
- The `scenario` column is a test aid only — strip it before sending rows to the ingestion API.
