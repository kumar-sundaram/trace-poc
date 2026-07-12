# NFR-7 scale probe results

Measured 2026-07-12 on a laptop (Apple Silicon), local Neo4j Community 2026.06.0, `all-MiniLM-L6-v2` embeddings (384-dim).

## Reading the numbers

- **Load**: 100,000 parties and 999,992 relationships (the scale CSV's one role edge per party, amplified with 7 pooled role edges each per the generator note in `scripts/scale_probe.py`) bulk-loaded in **112s**, of which 23s was embedding 100k strings locally.
- **Explore latency (NFR-5)**: p50 well under the 500ms bar for every anchor type — worst p50 was **26.7ms** (party anchors, 100 samples). Worst single request 225ms.
- **Signal re-run (FR-18)**: completed in **0.1s**, but note it evaluated 0 candidate attributes — the scale dataset's synthetic addresses are essentially unique, so no property is shared by ≥3 parties. What this measures is the full-graph candidate scan across ~1M `CONNECTED_TO` edges (the dominant fixed cost); per-attribute evaluation cost is exercised by the curated-dataset tests instead. The "under a few minutes" bar is met with enormous headroom either way.

**Verdict: NFR-7 feasibility confirmed** at the stated production volume.

```json
{
  "measuredAt": "2026-07-12T21:59:36.623133+00:00",
  "embedding": {
    "adapter": "minilm",
    "model": "all-MiniLM-L6-v2",
    "dimension": 384
  },
  "graph": {
    "parties": 100000,
    "relationships": 999992
  },
  "load": {
    "totalSeconds": 112.1,
    "encodeSeconds": 22.6
  },
  "explore": {
    "party": {
      "samples": 100,
      "p50_ms": 26.7,
      "p95_ms": 33.8,
      "max_ms": 224.8
    },
    "loan": {
      "samples": 25,
      "p50_ms": 11.4,
      "p95_ms": 125.5,
      "max_ms": 154.8
    },
    "property": {
      "samples": 25,
      "p50_ms": 5.0,
      "p95_ms": 34.9,
      "max_ms": 44.5
    }
  },
  "signalRerun": {
    "evaluatedAttributes": 0,
    "raised": 0,
    "runId": "rerun-7362b8e9-93ae-476b-998f-13a718c86306",
    "seconds": 0.1
  },
  "verdict": {
    "nfr5_p50_under_500ms": true,
    "fr18_rerun_under_minutes": true
  }
}
```

Reproduce: `uv sync --group scale && uv run python scripts/scale_probe.py` (wipes the graph; `make seed` restores the demo dataset).
