# Documentation

| Path | Contents |
|---|---|
| [../spec/party-network-poc-spec.md](../spec/party-network-poc-spec.md) | POC requirements specification (source of truth) |
| [contracts/](contracts/) | Versioned boundary contracts: ingestion request + outbound event schemas (§9 deliverables) |
| [test-data/](test-data/) | Synthetic seed CSVs, negative fixtures, scale probe, and generator |

## Test data

Regenerate all CSV fixtures:

```bash
python docs/test-data/generate_parties.py
```

See [test-data/README.md](test-data/README.md) for file descriptions and scenario mapping.
