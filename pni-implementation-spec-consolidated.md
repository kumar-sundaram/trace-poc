# Party Network Platform — Implementation Specification (Consolidated)

> Transcribed from Amazon Q output, pages 1–16. Capture ends mid-section 3.2 (Relationship Types); any later pages are not included.

---

## 1. FEATURE INVENTORY

### 1.1 Party Ingestion

**Feature: Accept party event**
- What: Validates and normalizes an inbound party event from a source system. Rejects contract violations synchronously. Acknowledges duplicates without reprocessing.
- Entry point: `POST /events`
- Input: `PartyEvent` JSON body
- Output: `202 AcceptResponse (status, duplicate, correlation)` or `422` on contract violation

**Feature: Idempotency guard**
- What: Checks whether a `(sourceSystem, eventId)` pair has already been processed by looking for an existing `RawRecord` node with `id = "{sourceSystem}:{eventId}"`. If found, returns `duplicate: true` and skips all processing.
- Entry point: called inside `POST /events` before resolution
- Input: `PartyEvent` → Output: boolean

**Feature: Name and address normalization**
- What: Produces canonical forms used for Tier-2 matching and graph storage. Applied at validation time; stored on `RawRecord` and `Party` nodes.
- Entry point: `PartyEvent.normalized_name` and `PartyEvent.normalized_address` properties, computed on demand
- Input: raw name fields or address string → Output: normalized string

### 1.2 Identity Resolution

**Feature: Tier-1 exact identifier match**
- What: Matches an incoming event to an existing `Party` by exact `ssnOrTaxId` and same `partyType`. Deterministic; highest confidence.
- Entry point: `Tier1ExactIdentifier.attempt()` in the pipeline chain
- Input: `MatchContext` (event + graph)
- Output: `MatchDecision(tier="T1", method="exact_identifier", confidence=1.0)` or `None`

**Feature: Tier-2 normalized name+address match**
- What: Matches by exact `normalizedName` on a `Party` node of the same `partyType` that is connected via `CONNECTED_TO` to a `Property` whose `normalizedAddress` equals the event's normalized address. Requires address to be present.
- Entry point: `Tier2NormalizedNameAddress.attempt()`
- Input: `MatchContext`
- Output: `MatchDecision(tier="T2", method="normalized_name_address", confidence=0.99)` or `None`

**Feature: Tier-3 vector similarity match**
- What: Queries the Neo4j vector index for the top-K most similar `Party` nodes of the same `partyType`. Applies address-less score cap. Auto-matches only when score ≥ `auto_match_threshold` AND `normalizedName` is exactly equal. Passes ambiguous candidates (score > `no_match_threshold` but below auto-match, or above auto-match but name differs) to Tier 4.
- Entry point: `Tier3VectorSimilarity.attempt()`
- Input: `MatchContext` (embedding computed lazily from name [+ address])
- Output: `MatchDecision(tier="T3", method="vector_similarity", confidence=score)` or `None`; populates `ctx.candidates` for Tier 4

**Feature: Tier-4 LLM disambiguation**
- What: Iterates over ambiguous candidates left by Tier 3. For each, calls the LLM client with the incoming and candidate `PartyDescriptor`. First `MATCH` judgment wins. `NO_MATCH` and `UNCERTAIN` both fall through; exhausting all candidates creates a new party.
- Entry point: `Tier4LLMDisambiguation.attempt()`
- Input: `MatchContext` with populated candidates
- Output: `MatchDecision(tier="T4", method="llm_disambiguation", confidence=candidate.score, rationale=…)` or `None`

**Feature: New party creation (fallback)**
- What: When all four tiers return `None`, a new `Party` node is created with a fresh UUID. Confidence is set to `addressless_confidence_cap` for address-less events, `1.0` otherwise. Method is `"new_party_name_only"` or `"new_party"`.
- Entry point: `ResolutionService.resolve()` after the pipeline loop
- Input: `MatchContext`
- Output: new `party_id`, writes `Party` node with embedding

**Feature: Party enrichment on match**
- What: When a match is found and the incoming event carries a `ssnOrTaxId` the matched party lacks, the identifier is written to the party node (`SET p.ssnOrTaxId = coalesce(p.ssnOrTaxId, $ssn)`).
- Entry point: `ResolutionService._enrich_party()`

**Feature: Graph write (single ACID transaction)**
- What: After the match phase, one managed write transaction creates/updates: `RawRecord`, `Party` (create or enrich), `RESOLVES_TO` edge, `Property` node + `CONNECTED_TO` edge (if address present), `Loan` node + `HAS_ROLE_ON` edge (if role present). All edges carry provenance.
- Entry point: `ResolutionService.resolve()` → `graph.execute_write(write)`

### 1.3 Graph Traversal (Explore)

**Feature: Anchored 2-hop traversal**
- What: Starting from a party, loan, or property anchor, performs a bounded BFS up to 2 hops over `CONNECTED_TO` and `HAS_ROLE_ON` edges. Before expanding each frontier node, checks its degree against the guard threshold. Annotates party nodes with their resolution tiers and active signal flags.
- Entry point: `GET /explore?anchorType=&q=`
- Input: `anchorType` (party | loan | property), `q` (id, name, loanRef, or address)
- Output: `ExploreResult` (anchor, nodes, edges, guards, flags)

**Feature: Anchor resolution**
- What: Finds the anchor node. For `party`: matches by `p.id = q` OR `p.normalizedName IN [base_normalize(q), normalize_entity_name(q)]`, ordered by `createdAt`, limit 1. For `loan`: exact `Loan.id`. For `property`: exact match on `p.id IN [q, normalize_address(q)]`.
- Entry point: `ExploreService._find_anchor()`

**Feature: Degree guard**
- What: Before expanding any frontier node, queries `COUNT { (n)--() }`. If degree > `degree_guard_threshold` (default 200), the node is added to `guards` list as a `GuardMarker` and not expanded. Applies to all node types.
- Entry point: `ExploreService._apply_degree_guard()`

**Feature: Signal flag annotation**
- What: After traversal, queries for `Signal` nodes with `status='RAISED'` whose `relatedPartyIds` array contains any party in the result set. Returns `SignalFlag(partyId, signalId, patternType)` for each match.
- Entry point: `ExploreService._signal_flags()`

**Feature: Resolution tier annotation**
- What: For each party in the result, collects distinct `tier` values from all `RESOLVES_TO` edges pointing to it and stores them as `resolutionTiers` in the node's properties.
- Entry point: `ExploreService._attach_resolution_tiers()`

**Feature: Overview (all nodes of a type)**
- What: Returns all non-degree-guarded nodes of a given type. For `Party`: finds bridging edges between party pairs that share a common intermediary (loan or property) also below the degree guard. For `Loan` / `Property`: returns direct party connections.
- Entry point: `GET /overview?nodeType=` (party | loan | property)
- Output: `ExploreResult`

### 1.4 Signal Detection

**Feature: Attribute fan-out rule**
- What: For a given `Property` node, finds all parties connected to it via `CONNECTED_TO {source: 'shared_attribute'}` that also have loans. Anchors on the newest `originatedAt` among those loans. Counts distinct parties whose loans fall within the `fanout_window_days` window. If count ≥ `fanout_min_parties`, raises a signal. Severity is `MEDIUM` if count equals the minimum, `HIGH` if greater.
- Entry point: `SignalService._evaluate_attribute()`, called post-write and via `POST /admin/signals/rerun`
- Input: `property_id`, `source_system`, `causation_event_id`
- Output: `SignalPayload` or `None`

**Feature: Shell cluster rule**
- What: For a given party, checks if it acts as `GUARANTOR` or `SPONSOR` on loans where other `ENTITY` parties are borrowers, and those entity parties share a common address with still other entity parties. If the co-located shell count ≥ `fanout_min_parties`, raises a signal.
- Entry point: `SignalService._evaluate_shell_cluster()`
- Severity: `MEDIUM` if count equals minimum, `HIGH` if greater

**Feature: Circular role network rule**
- What: Detects Party A as `SPONSOR` on a loan where Party B is `BORROWER`, and Party B as `SPONSOR` on a different loan where Party A is `BORROWER`. Raises a `HIGH` severity signal.
- Entry point: `SignalService._evaluate_circular_role()`

**Feature: Loan velocity rule**
- What: For a given party, finds all loans, anchors on the newest `originatedAt`, counts loans within `fanout_window_days` of that anchor. If count ≥ `velocity_min_loans`, raises a signal. Severity `MEDIUM` at minimum, `HIGH` above.
- Entry point: `SignalService._evaluate_loan_velocity()`

**Feature: Post-write signal hook**
- What: After each successful graph write, evaluates only the rules that could have been affected: attribute fan-out on the event's address (if present), shell cluster and circular role on the resolved party, loan velocity if the event carried a role.
- Entry point: `SignalService.evaluate_event()`, wired as `post_write_hook` in `ResolutionService`

**Feature: Full-graph signal re-run**
- What: Scans all properties with ≥ `fanout_min_parties` connected parties, then all parties, running all four rules. Returns counts of evaluated attributes and raised signals.
- Entry point: `POST /admin/signals/rerun`
- Output: `{"evaluatedAttributes": int, "raised": int, "runId": str}`

**Feature: Signal idempotency**
- What: Signal identity is `sha1("{patternType}|{attributeId}")[:16]` prefixed with `"sig-"`. Uses `MERGE` on `Signal.id`; returns `False` (already exists) if the node was not just created. A growing cluster does not re-fire.
- Entry point: `SignalService._create_signal_node()`

**Feature: Degree guard on signal evaluation**
- What: Before evaluating attribute fan-out for a property, checks its degree. If > `degree_guard_threshold`, skips evaluation and reclassifies any previously `RAISED` signals on that attribute to `EXCLUDED_DEGREE_GUARD` (not deleted).
- Entry point: `SignalService._evaluate_attribute()`

**Feature: List signals**
- What: Returns all `Signal` nodes with `status='RAISED'`, ordered by `raisedAt` descending.
- Entry point: `GET /signals`
- Output: `list[SignalView]`

### 1.5 Event Emission

**Feature: Resolution outcome event**
- What: After each successful graph write, appends a JSONL line to `data/streams/resolution-outcome.jsonl`. Envelope carries `eventType`, `schemaVersion`, `sourceSystem`, `eventId`, `timestamp`, and a `ResolutionOutcomePayload`.
- Entry point: `EventEmitter.emit_resolution_outcome()`, called in `ResolutionService.resolve()`

**Feature: Signal event**
- What: When a signal is newly raised, appends a JSONL line to `data/streams/signal.jsonl`. Same envelope structure with a `SignalPayload`.
- Entry point: `EventEmitter.emit_signal()`, called in each `_evaluate_*` method

### 1.6 Admin / Seeding

**Feature: Demo reset**
- What: Wipes all graph data (schema survives, batched in 10,000-row transactions), truncates both JSONL stream files, then replays the curated CSV through the real ingestion path.
- Entry point: `POST /admin/reset` or `python -m api.seeding`
- Output: `{"clearedNodes": int, "events": int, "duplicatesAbsorbed": int, "parties": int, "rawRecords": int, "raisedSignals": int, "elapsedSeconds": float}`

**Feature: Graph stats**
- What: Returns aggregate counts (parties, loans, properties, role edges, raised signals) plus top-party-by-loans, top-loan-by-parties, and top-address-by-parties (capped at degree ≤ 200).
- Entry point: `GET /stats` → Output: `GraphStats` dict

**Feature: Health check**
- What: Returns app status, Neo4j reachability (via `RETURN 1`), known source systems, and role vocabulary.
- Entry point: `GET /healthz`
- Output: `{"status": "ok", "neo4j": "ok"|"unreachable", "knownSourceSystems": […], "roleVocabulary": […]}`

### 1.7 UI

**Feature: Homepage with stats**
- What: Displays party/loan/property/signal counts as clickable buttons. Clicking a count triggers an overview for that node type. Includes a search form.
- Entry point: App load, `GET /stats`

**Feature: Search / explore form**
- What: Anchor type selector (party | loan | property) + free-text input. Submits to `GET /explore`. Resets filters on each new search.
- Entry point: form submit → `explore(anchorType, q)`

**Feature: Force-directed graph view**
- What: Renders `ExploreResult` as a 2D force graph using `react-force-graph-2d`. Nodes are pill-shaped, color-coded by type (Party=#4c8dff, Property=#3dbb7e, Loan=#e8a13c, Anchor=#f0c040). Flagged parties get a red border (#e05252). Edges show role/type labels at midpoint. Bridged edges (hidden intermediary) are dashed gray. Anchor node is pinned at origin (fx=0, fy=0). Charge strength −300, link distance 110. Auto-zooms to fit on engine stop.
- Entry point: `ExploreResult` state change

**Feature: Graph filters**
- What: Toggle visibility of node types (Party/Property/Loan), hop depth (1 or 2), and role filter (dropdown of roles present in current result). Anchor type is always visible. Hidden intermediary nodes produce bridging edges between their visible party neighbors.
- Entry point: filter button/select interactions

**Feature: Node detail panel**
- What: Single-click selects a node and shows its properties. Known keys are mapped to human labels (`displayName` → Name, `rawAddress` → Address, etc.). `id`, `embedding`, `normalizedName`, `normalizedAddress` are hidden. ISO datetime strings are formatted. `loanAmount` is formatted as USD currency. Extra (unknown) keys are in a collapsible section. Double-click re-anchors the explore to that node.
- Entry point: node click

**Feature: Shared loans / parties at address panel**
- What: For a selected Party node, lists loans it shares with other parties (with co-party roles). For a selected Loan, lists all parties and their roles. For a selected Property, lists parties at that address and loans associated with them.
- Entry point: node selection

**Feature: Graph narrative**
- What: A prose summary above the graph describing the anchor's connections, co-parties, roles, source systems, resolution tiers, signal flags, and degree-guarded nodes. Clickable links re-anchor the explore.
- Entry point: `ExploreResult` state change

**Feature: Fraud signals tab**
- What: Lists all raised signals as cards with severity badge, pattern label, timestamp, attribute ID, generated narrative, related party links (truncated UUIDs), and collapsible evidence path. Filterable by severity (HIGH/MEDIUM/LOW) and pattern type. Signal count badge on tab.
- Entry point: `GET /signals`, tab click

**Feature: Demo reset button**
- What: Confirms with `window.confirm`, calls `POST /admin/reset`, clears graph state, refreshes signals.
- Entry point: header button

---

## 2. RECENT/UNIQUE LOGIC

### 2.1 Normalization Rules

**Base normalization** (applied to all names and addresses):
```
text = text.upper()
text = strip all non-word, non-space characters (regex [^\w\s])
text = collapse all whitespace runs to single space
text = strip leading/trailing whitespace
```

**Individual name normalization:**
```
parts = [firstName]
if middleName: parts.append(middleName)
parts.append(lastName)
return base_normalize(join(parts, " "))
```

**Entity name normalization:**
```
name = base_normalize(entityName)
# Multi-word suffix phrases checked first (order matters):
#   "LIMITED LIABILITY COMPANY"    -> "LLC"
#   "LIMITED LIABILITY PARTNERSHIP" -> "LLP"
#   "LIMITED PARTNERSHIP"           -> "LP"
for phrase, abbrev in PHRASE_MAP:
    if name ends with " " + phrase:
        replace suffix with abbrev; break
# Single-token suffix normalization on last token:
token_map = {LLC->LLC, LLP->LLP, LP->LP, INCORPORATED->INC, INC->INC,
             CORPORATION->CORP, CORP->CORP, COMPANY->CO, CO->CO,
             LIMITED->LTD, LTD->LTD}
if last token in token_map: replace last token
return name
```

**Address normalization:**
```
tokens = base_normalize(address).split(" ")
for each token: replace with USPS abbreviation if in map, else keep
# Abbreviation map (partial): STREET->ST, AVENUE->AVE, BOULEVARD->BLVD,
# DRIVE->DR, LANE->LN, ROAD->RD, COURT->CT, PLACE->PL, PLAZA->PLZ,
# POINT->PT, PARKWAY->PKWY, HIGHWAY->HWY, CIRCLE->CIR, TERRACE->TER,
# TRAIL->TRL, SQUARE->SQ, EXPRESSWAY->EXPY, FREEWAY->FWY,
# SUITE->STE, APARTMENT->APT, BUILDING->BLDG, FLOOR->FL,
# NORTH->N, SOUTH->S, EAST->E, WEST->W,
# NORTHEAST->NE, NORTHWEST->NW, SOUTHEAST->SE, SOUTHWEST->SW
```

### 2.2 Ingestion Validation Rules

Pydantic `model_validator` enforces (in order, all-or-nothing):
1. Blank strings are coerced to `None` before type checks.
2. `partyType == "INDIVIDUAL"` requires both `firstName` and `lastName` non-null.
3. `partyType == "ENTITY"` requires `entityName` non-null.
4. `sourceSystem` must be in `known_source_systems` list (from config).
5. If `role` is present: must be in `role_vocabulary` (from config); `loanRef` must also be present.
6. If `role == "BORROWER"`: `address` must be present.

`raw_record_id = "{sourceSystem}:{eventId}"` (deterministic, used as `RawRecord.id`).

### 2.3 Resolution Pipeline

```
ctx = MatchContext(event, graph, settings, embedding_client, llm_client)
decision = None
for stage in [Tier1, Tier2, Tier3, Tier4]:
    decision = stage.attempt(ctx)
    if decision is not None: break
if decision is None:
    party_id = new UUID
    confidence = addressless_confidence_cap if no address else 1.0
    method = "new_party_name_only" if no address else "new_party"
    embedding = ctx.embedding   # already computed by Tier3
else:
    party_id = decision.party_id
    confidence = decision.confidence
    method = decision.method
    embedding = None            # not needed; party already exists
execute single ACID write transaction
emit resolution-outcome event
call post_write_hook(event, party_id)
```

**Tier-3 embedding input:**
```
text = normalized_name
if normalized_address: text = normalized_name + " " + normalized_address
embedding = embedding_client.embed(text)
```

**Tier-3 scoring and filtering:**
```
candidates = vector_index.query(embedding, k=vector_top_k, filter=partyType)
# Each candidate has: party_id, normalized_name, normalized_address, score
# Score is in Neo4j vector space: (1 + cosine) / 2
if event has no address:
    for each candidate: score = min(score, addressless_confidence_cap)  # cap = 0.85
candidates = [c for c in candidates if c.score > no_match_threshold]    # 0.75
candidates.sort(by score, descending)
if candidates[0].score >= auto_match_threshold                          # 0.92
   AND candidates[0].normalized_name == event.normalized_name:
    return MatchDecision(T3, score)
ctx.candidates = candidates   # pass to Tier 4
return None
```

**Tier-4 mock LLM logic:**
```
if incoming.party_type != candidate.party_type:
    return NO_MATCH ("party types differ")
digits_a = sorted numeric tokens in incoming.normalized_name
digits_b = sorted numeric tokens in candidate.normalized_name
if digits_a != digits_b:
    return NO_MATCH ("numeric name tokens differ; distinct registrations")
if party_type == "INDIVIDUAL":
    if last token of incoming.name != last token of candidate.name:
        return NO_MATCH ("last names differ")
ratio = SequenceMatcher(incoming.normalized_name, candidate.normalized_name).ratio()
if ratio >= 0.78: return MATCH
if ratio <= 0.50: return NO_MATCH
return UNCERTAIN
```

### 2.4 Hash Embedding (local fallback)

```
vector = [0.0] * dimension
padded = " " + text.upper() + " "
for i in range(len(padded) - 2):
    trigram = padded[i:i+3]
    digest  = md5(trigram.encode()).digest()
    index   = int.from_bytes(digest[:4], "big") % dimension
    sign    = +1.0 if digest[4] % 2 == 0 else -1.0
    vector[index] += sign
norm = sqrt(sum(v*v for v in vector)) or 1.0
return [v / norm for v in vector]
```

### 2.5 Graph Write Details

**RawRecord creation — always `CREATE`** (never MERGE; idempotency is checked before this point):
- Properties: `id`, `sourceSystem`, `eventId`, `partyType`, `firstName`, `middleName`, `lastName`, `entityName`, `address`, `ssnOrTaxId`, `role`, `loanRef`, `normalizedName`, `normalizedAddress`, `receivedAt` (UTC ISO string)

**Party creation (new party only):**
- `displayName = "{firstName} {lastName}"` for INDIVIDUAL, `entityName` for ENTITY
- Embedding stored via `db.create.setNodeVectorProperty(p, 'embedding', $embedding)`
- Properties: `id`, `partyType`, `displayName`, `normalizedName`, `normalizedAddress`, `ssnOrTaxId`, `createdAt`, `sourceSystem`, `eventId`

**RESOLVES_TO edge (RawRecord → Party):**
- Properties: `tier`, `method`, `confidence`, `rationale`, `sourceSystem`, `eventId`, `resolvedAt`

**Property node + CONNECTED_TO edge:**
- `MERGE (prop:Property {id: $normalizedAddress})` — property id IS the normalized address
- `ON CREATE SET prop.normalizedAddress, prop.rawAddress`
- `MERGE (p)-[c:CONNECTED_TO]->(prop)` — one edge per party-property pair
- `ON CREATE SET c.tier='T4', c.source='shared_attribute', c.sourceSystem, c.eventId`

**Loan node + HAS_ROLE_ON edge:**
- `MERGE (l:Loan {id: $loanRef})`
- `ON CREATE SET l.originatedAt = $now`
- `MERGE (p)-[r:HAS_ROLE_ON {role: $role}]->(l)` — edge identity is (party, loan, role)
- `ON CREATE SET r.tier, r.source='event_role', r.sourceSystem, r.eventId`

### 2.6 Signal Rules Detail

**Attribute fan-out:**
```
degree = COUNT { (prop)--() }
if degree > degree_guard_threshold:
    reclassify existing RAISED signals to EXCLUDED_DEGREE_GUARD
    return None
rows = MATCH (prop)<-[:CONNECTED_TO {source:'shared_attribute'}]-(p:Party)
             -[:HAS_ROLE_ON]->(l:Loan)
       RETURN p.id, l.id, l.originatedAt
anchor       = max(datetime(r.originatedAt) for r in rows)
window_start = anchor - timedelta(days=fanout_window_days)   # 14
in_window    = [r for r in rows if r.originatedAt >= window_start]
parties      = distinct party IDs in in_window
if len(parties) < fanout_min_parties:                        # 3
    return None
signal_id = "sig-" + sha1("attribute_fanout|{property_id}").hexdigest()[:16]
severity  = "MEDIUM" if len(parties) == 3 else "HIGH"
evidence  = ["Property:{id}"] + ["Party:{pid}->Loan:{lid}" for each row in in_window]
```

**Signal node MERGE (idempotency):**
```
MERGE (s:Signal {id: $id})
ON CREATE SET s.patternType, s.relatedPartyIds, s.evidencePath,
              s.severity, s.status='RAISED', s.attributeId,
              s.causationEventId, s.raisedAt=datetime(), s.justCreated=true
ON MATCH  SET s.justCreated = false
# returns created boolean; if false, signal already existed -> skip emit
```

**Signal ID formula** (all patterns except attribute_fanout use `_make_signal_id`):
```
signal_id = "sig-" + sha1("{patternType}|{key}").hexdigest()[:16]
# key for shell_cluster:          property_id
# key for circular_role_network:  sorted([partyA_id, partyB_id]).join("|")
# key for loan_velocity:          party_id
# attribute_fanout uses _signal_id (same formula, kept for backward compat)
```

### 2.7 Explore Traversal Detail

```
MAX_HOPS = 2
anchor  = find_anchor(anchor_type, query)
nodes   = {anchor.id: anchor}
edges   = {}
guards  = []
frontier = {anchor.nodeType: [anchor.id]}
for hop in 1..MAX_HOPS:
    expandable = apply_degree_guard(frontier, nodes, guards)
    if no expandable ids: break
    for label, ids in expandable:
        for row in expand(label, ids):
            # expand query: MATCH (n:{label}) WHERE n.id IN $ids
            #               MATCH (n)-[e:CONNECTED_TO|HAS_ROLE_ON]-(m)
            #               RETURN n.id, type(e), properties(e),
            #                      m.id, labels(m)[0], properties(m)
            if neighbor not in nodes: add to nodes, add to next_frontier
            edges.setdefault((source, target, type, role), edge)
    frontier = next_frontier
attach_resolution_tiers(party_ids, nodes)
flags = signal_flags(party_ids)
return ExploreResult(anchor, nodes, edges, guards, flags)
```

- Edge orientation: always `source=Party`, `target=Property|Loan`. When expansion is from a non-Party node, source and target are swapped to maintain this invariant.
- `_HIDDEN_PARTY_PROPS = {"embedding"}` — excluded from all node property responses.

---

## 3. DATA MODEL

### 3.1 Node Labels and Properties

**Party**

| Property | Type | Required | Notes |
|---|---|---|---|
| id | string (UUID) | yes | unique constraint |
| partyType | "INDIVIDUAL" \| "ENTITY" | yes | |
| displayName | string | yes | raw display form |
| normalizedName | string | yes | indexed |
| normalizedAddress | string | no | address of first event |
| ssnOrTaxId | string | no | enriched on match |
| createdAt | ISO datetime string | yes | |
| sourceSystem | string | yes | first event's source |
| eventId | string | yes | first event's id |
| embedding | float[] | yes (on create) | vector index; hidden from API |

**Property**

| Property | Type | Required | Notes |
|---|---|---|---|
| id | string | yes | = normalizedAddress; unique constraint |
| normalizedAddress | string | yes | indexed |
| rawAddress | string | yes | original submitted address |

**Loan**

| Property | Type | Required | Notes |
|---|---|---|---|
| id | string | yes | = loanRef; unique constraint |
| originatedAt | ISO datetime string | yes | set on first MERGE (processing time) |

**RawRecord**

| Property | Type | Required | Notes |
|---|---|---|---|
| id | string | yes | "{sourceSystem}:{eventId}"; unique constraint |
| sourceSystem | string | yes | |
| eventId | string | yes | |
| partyType | string | yes | |
| firstName | string | no | |
| middleName | string | no | |
| lastName | string | no | |
| entityName | string | no | |
| address | string | no | raw |
| ssnOrTaxId | string | no | |
| role | string | no | |
| loanRef | string | no | |
| normalizedName | string | yes | |
| normalizedAddress | string | no | |
| receivedAt | ISO datetime string | yes | |

**Signal**

| Property | Type | Required | Notes |
|---|---|---|---|
| id | string | yes | "sig-{sha1[:16]}"; unique constraint |
| patternType | string | yes | one of four pattern constants |
| relatedPartyIds | string[] | yes | |
| evidencePath | string[] | yes | ordered node/edge refs |
| severity | "LOW" \| "MEDIUM" \| "HIGH" | yes | |
| status | "RAISED" \| "EXCLUDED_DEGREE_GUARD" | yes | |
| attributeId | string | yes | property_id or party_id or role-pair key |
| causationEventId | string | yes | |
| raisedAt | datetime | yes | Neo4j datetime() |

### 3.2 Relationship Types and Properties

**RESOLVES_TO** (RawRecord → Party)

| Property | Required | Notes |
|---|---|---|
| tier | no | "T1"–"T4" or null for new party |

> ⚠️ Transcription ends here — page 16 cuts off mid-table. Remaining relationship property tables (RESOLVES_TO continued, CONNECTED_TO, HAS_ROLE_ON) and any sections after 3.2 (likely API surface, configuration, known gaps) were not captured.

---

## Key configuration constants (as captured)

| Constant | Value |
|---|---|
| auto_match_threshold (T3) | 0.92 |
| no_match_threshold (T3) | 0.75 |
| addressless_confidence_cap | 0.85 |
| T4 SequenceMatcher MATCH | ratio ≥ 0.78 |
| T4 SequenceMatcher NO_MATCH | ratio ≤ 0.50 |
| degree_guard_threshold | 200 |
| fanout_window_days | 14 |
| fanout_min_parties | 3 |
| MAX_HOPS (explore) | 2 |
| Demo reset batch size | 10,000 rows/txn |

## Demo-worthy UI moments (for the deck)

1. **Search → network expansion** — type a party name, watch the anchored 2-hop force graph render with color-coded pills and the anchor pinned at center.
2. **Signal flag on the graph** — a flagged party's red border (#e05252) draws the eye immediately; click it and the narrative explains why.
3. **Graph narrative with clickable pivots** — prose summary above the graph; clicking a linked entity re-anchors the exploration (investigator workflow in one gesture).
4. **Fraud signals tab** — severity-badged cards with collapsible evidence paths; filter to HIGH and walk one signal end-to-end.
5. **Double-click re-anchor** — traverse the network hop by hop without ever typing a second query.
6. **Demo reset** — one button returns to a clean, seeded state (useful as your own safety net, not necessarily shown).
