"""NFR-7 scale probe: bulk-load ~100k parties / ~1M relationships, then
measure Explore latency (NFR-5) and a full-graph signal re-run (FR-18).

This is a one-time feasibility measurement, not scale engineering. Per NFR-7
the generator *bulk-loads* — rows bypass the per-event HTTP pipeline but
produce the same graph shape with full provenance. The scale CSV supplies one
role edge per party (~300k relationships total); the generator amplifies each
party with extra role edges drawn deterministically from the loan pool to
reach the spec's ~1M relationships.

Usage:
    uv sync --group scale        # once — installs sentence-transformers
    uv run python scripts/scale_probe.py

Runs on local MiniLM embeddings (decided 2026-07-12; free/offline, realistic
vector distribution). Wipes the graph first; run `make seed` afterwards to
restore the demo dataset (bootstrap recreates the 512-dim Titan index).
"""

import csv
import json
import os
import random
import statistics
import sys
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter

# Configure the embedding stack before any api import reads settings.
os.environ.setdefault("TRACE_EMBEDDING__ADAPTER", "minilm")
os.environ.setdefault("TRACE_EMBEDDING__MODEL", "all-MiniLM-L6-v2")
os.environ.setdefault("TRACE_EMBEDDING__DIMENSION", "384")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from api.config import REPO_ROOT, get_settings  # noqa: E402
from api.normalize import normalize_address, normalize_name  # noqa: E402
from api.resolve.adapters import build_embedding_client  # noqa: E402

SCALE_CSV = REPO_ROOT / "docs" / "test-data" / "party_network_scale_100k.csv"
RESULTS_MD = REPO_ROOT / "docs" / "scale-probe-results.md"
CHUNK = 2000          # rows encoded+written per iteration (memory-bounded)
WRITE_BATCH = 1000    # rows per write transaction
EXTRA_ROLE_EDGES = 7  # per party, on pooled loans → ~1M relationships total
EXPLORE_SAMPLES = {"party": 100, "loan": 25, "property": 25}

BULK_WRITE = """
UNWIND $rows AS row
CREATE (r:RawRecord {id: row.rawId, sourceSystem: row.sourceSystem,
    eventId: row.eventId, partyType: row.partyType, firstName: row.firstName,
    lastName: row.lastName, entityName: row.entityName, address: row.address,
    ssnOrTaxId: row.ssn, role: row.role, loanRef: row.loanRef,
    normalizedName: row.normalizedName, normalizedAddress: row.normalizedAddress,
    receivedAt: $now})
CREATE (p:Party {id: row.partyId, partyType: row.partyType,
    displayName: row.displayName, normalizedName: row.normalizedName,
    normalizedAddress: row.normalizedAddress, ssnOrTaxId: row.ssn,
    createdAt: $now, sourceSystem: row.sourceSystem, eventId: row.eventId})
CREATE (r)-[:RESOLVES_TO {tier: null, method: 'bulk_load', confidence: 1.0,
    sourceSystem: row.sourceSystem, eventId: row.eventId, resolvedAt: $now}]->(p)
WITH row, p
CALL db.create.setNodeVectorProperty(p, 'embedding', row.embedding)
MERGE (prop:Property {id: row.normalizedAddress})
ON CREATE SET prop.normalizedAddress = row.normalizedAddress,
              prop.rawAddress = row.address
MERGE (p)-[c:CONNECTED_TO]->(prop)
ON CREATE SET c.tier = 'T4', c.source = 'shared_attribute',
              c.sourceSystem = row.sourceSystem, c.eventId = row.eventId
WITH row, p
UNWIND row.loans AS loan
MERGE (l:Loan {id: loan.loanRef})
ON CREATE SET l.originatedAt = $now
MERGE (p)-[h:HAS_ROLE_ON {role: loan.role}]->(l)
ON CREATE SET h.tier = 'NEW', h.source = 'event_role',
              h.sourceSystem = row.sourceSystem, h.eventId = loan.eventId
"""


def read_rows() -> list[dict]:
    with open(SCALE_CSV) as f:
        return list(csv.DictReader(f))


def prepare(row: dict, rng: random.Random, loan_pool: list[str], roles: list[str]) -> dict:
    normalized_name = normalize_name(
        row["partyType"],
        first_name=row["firstName"],
        last_name=row["lastName"],
        entity_name=row["entityName"],
    )
    loans = [{"loanRef": row["loanRef"], "role": row["role"], "eventId": row["eventId"]}]
    for i in range(EXTRA_ROLE_EDGES):
        loans.append(
            {
                "loanRef": rng.choice(loan_pool),
                "role": rng.choice(roles),
                "eventId": f"{row['eventId']}#amp{i}",
            }
        )
    return {
        "rawId": f"{row['sourceSystem']}:{row['eventId']}",
        "partyId": f"scale-{row['eventId']}",
        "sourceSystem": row["sourceSystem"],
        "eventId": row["eventId"],
        "partyType": row["partyType"],
        "firstName": row["firstName"] or None,
        "lastName": row["lastName"] or None,
        "entityName": row["entityName"] or None,
        "displayName": (
            f"{row['firstName']} {row['lastName']}"
            if row["partyType"] == "INDIVIDUAL"
            else row["entityName"]
        ),
        "address": row["address"],
        "ssn": row["ssnOrTaxId"] or None,
        "role": row["role"],
        "loanRef": row["loanRef"],
        "normalizedName": normalized_name,
        "normalizedAddress": normalize_address(row["address"]),
        "loans": loans,
    }


def percentile(values: list[float], pct: float) -> float:
    return statistics.quantiles(values, n=100)[int(pct) - 1]


def main() -> None:
    settings = get_settings()
    from api.services import build_services

    services = build_services(settings)
    graph = services.graph
    embedder = build_embedding_client(settings)

    print("wiping graph …")
    graph.wipe()
    services.emitter.reset()
    graph.bootstrap_schema()  # ensure the 384-dim index

    rows = read_rows()
    rng = random.Random(42)
    loan_pool = [r["loanRef"] for r in rows]
    roles = settings.role_vocabulary
    print(f"loading {len(rows)} rows (chunk={CHUNK}, +{EXTRA_ROLE_EDGES} role edges each) …")

    now = datetime.now(UTC).isoformat()
    load_start = perf_counter()
    encode_seconds = 0.0
    for start in range(0, len(rows), CHUNK):
        chunk = [prepare(r, rng, loan_pool, roles) for r in rows[start : start + CHUNK]]
        texts = [f"{c['normalizedName']} {c['normalizedAddress']}" for c in chunk]
        t = perf_counter()
        vectors = embedder.embed_batch(texts)
        encode_seconds += perf_counter() - t
        for c, v in zip(chunk, vectors):
            c["embedding"] = v
        for w in range(0, len(chunk), WRITE_BATCH):
            batch = chunk[w : w + WRITE_BATCH]
            graph.execute_write(lambda tx, batch=batch: tx.run(BULK_WRITE, rows=batch, now=now))
        if (start // CHUNK) % 5 == 0:
            print(f"  {start + len(chunk):>6}/{len(rows)}  ({perf_counter() - load_start:.0f}s)")
    load_seconds = perf_counter() - load_start

    counts = graph.execute_read(
        lambda tx: tx.run(
            "MATCH (p:Party) WITH count(p) AS parties "
            "MATCH ()-[r]->() RETURN parties, count(r) AS relationships"
        ).single()
    )
    print(f"loaded: {counts['parties']} parties, {counts['relationships']} relationships "
          f"in {load_seconds:.0f}s (encode {encode_seconds:.0f}s)")

    # --- measurements over the HTTP path -----------------------------------
    from fastapi.testclient import TestClient

    from api.main import create_app

    sample_ids = graph.execute_read(
        lambda tx: {
            "party": [r["id"] for r in tx.run(
                "MATCH (p:Party) WITH p ORDER BY rand() LIMIT $n RETURN p.id AS id",
                n=EXPLORE_SAMPLES["party"])],
            "loan": [r["id"] for r in tx.run(
                "MATCH (l:Loan) WITH l ORDER BY rand() LIMIT $n RETURN l.id AS id",
                n=EXPLORE_SAMPLES["loan"])],
            "property": [r["id"] for r in tx.run(
                "MATCH (pr:Property) WITH pr ORDER BY rand() LIMIT $n RETURN pr.id AS id",
                n=EXPLORE_SAMPLES["property"])],
        }
    )

    explore_stats = {}
    with TestClient(create_app()) as client:
        for anchor_type, ids in sample_ids.items():
            timings = []
            for anchor_id in ids:
                t = perf_counter()
                resp = client.get("/explore", params={"anchorType": anchor_type, "q": anchor_id})
                timings.append((perf_counter() - t) * 1000)
                assert resp.status_code == 200, resp.text
            explore_stats[anchor_type] = {
                "samples": len(timings),
                "p50_ms": round(statistics.median(timings), 1),
                "p95_ms": round(percentile(timings, 95), 1),
                "max_ms": round(max(timings), 1),
            }
            print(f"explore[{anchor_type}]: {explore_stats[anchor_type]}")

        t = perf_counter()
        rerun = client.post("/admin/signals/rerun").json()
        rerun_seconds = perf_counter() - t
        print(f"signal re-run: {rerun} in {rerun_seconds:.1f}s")

    report = {
        "measuredAt": now,
        "embedding": {"adapter": settings.embedding.adapter, "model": settings.embedding.model,
                      "dimension": settings.embedding.dimension},
        "graph": dict(counts),
        "load": {"totalSeconds": round(load_seconds, 1),
                 "encodeSeconds": round(encode_seconds, 1)},
        "explore": explore_stats,
        "signalRerun": {**rerun, "seconds": round(rerun_seconds, 1)},
        "verdict": {
            "nfr5_p50_under_500ms": all(s["p50_ms"] < 500 for s in explore_stats.values()),
            "fr18_rerun_under_minutes": rerun_seconds < 300,
        },
    }
    print(json.dumps(report, indent=2))

    RESULTS_MD.write_text(
        "# NFR-7 scale probe results\n\n"
        f"Measured {now} on a laptop (Apple Silicon), Neo4j Community "
        f"{'' } local instance, `{settings.embedding.model}` embeddings.\n\n"
        "```json\n" + json.dumps(report, indent=2) + "\n```\n\n"
        "Reproduce: `uv sync --group scale && uv run python scripts/scale_probe.py` "
        "(wipes the graph; `make seed` restores the demo dataset).\n"
    )
    print(f"results written to {RESULTS_MD}")
    services.graph.close()


if __name__ == "__main__":
    main()
