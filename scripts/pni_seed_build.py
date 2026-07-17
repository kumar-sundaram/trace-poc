#!/usr/bin/env python3
"""
PNI demo seed builder — run at HOME, ship the output to work.

What it does
------------
1. Generates a deterministic synthetic dataset (~260 parties / ~300 loans)
   shaped like multifamily, with the four signal patterns planted.
2. Generates six hand-built entity-resolution cases — one per tier, plus two
   refusals — for you to fire live during the demo.
3. Embeds every text the pipeline will ever need with real MiniLM, and writes
   a text -> vector lookup table. At work, a PrecomputedEmbeddingClient reads
   this: real semantics, zero network, no LARS dependency.
4. CALIBRATES: prints which tier each demo case will actually hit, using your
   real thresholds. Do not skip this output — it is the point of the script.

Usage
-----
    pip install sentence-transformers
    python pni_seed_build.py --out ./data

Outputs
-------
    data/seed_events.json       seed corpus, POST these through /events
    data/demo_events.json       the six live resolution cases
    data/embeddings.json        {text: [384 floats]} lookup table
    data/calibration.md         the report, also printed to stdout

PRIVACY: everything here is synthetic. No real party data. Safe to move.
"""

import argparse, json, random, re, sys
from datetime import datetime, timedelta
from difflib import SequenceMatcher
from pathlib import Path

SEED = 20260717
random.seed(SEED)

# ---------------------------------------------------------------- thresholds
# These MUST mirror your settings. Spec §2.3.
AUTO_MATCH_THRESHOLD = 0.92      # neo4j vector space
NO_MATCH_THRESHOLD = 0.75        # neo4j vector space
ADDRESSLESS_CONFIDENCE_CAP = 0.85
T4_MATCH_RATIO = 0.78
T4_NO_MATCH_RATIO = 0.50
FANOUT_WINDOW_DAYS = 14
FANOUT_MIN_PARTIES = 3

# Neo4j returns score = (1 + cosine) / 2.  Inverting the thresholds:
#   score 0.92 -> cosine 0.84      <- auto-match needs cosine >= 0.84
#   score 0.75 -> cosine 0.50      <- below this, candidate is discarded
COS_AUTO = 2 * AUTO_MATCH_THRESHOLD - 1
COS_NOMATCH = 2 * NO_MATCH_THRESHOLD - 1

# ------------------------------------------------------------- normalization
# Faithful to spec §2.1. If your code drifts from this, the calibration lies.

def base_normalize(text: str) -> str:
    text = text.upper()
    text = re.sub(r"[^\w\s]", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()

PHRASE_MAP = [
    ("LIMITED LIABILITY COMPANY", "LLC"),
    ("LIMITED LIABILITY PARTNERSHIP", "LLP"),
    ("LIMITED PARTNERSHIP", "LP"),
]
TOKEN_MAP = {
    "LLC": "LLC", "LLP": "LLP", "LP": "LP", "INCORPORATED": "INC", "INC": "INC",
    "CORPORATION": "CORP", "CORP": "CORP", "COMPANY": "CO", "CO": "CO",
    "LIMITED": "LTD", "LTD": "LTD",
}
ADDR_MAP = {
    "STREET": "ST", "AVENUE": "AVE", "BOULEVARD": "BLVD", "DRIVE": "DR",
    "LANE": "LN", "ROAD": "RD", "COURT": "CT", "PLACE": "PL", "PLAZA": "PLZ",
    "POINT": "PT", "PARKWAY": "PKWY", "HIGHWAY": "HWY", "CIRCLE": "CIR",
    "TERRACE": "TER", "TRAIL": "TRL", "SQUARE": "SQ", "EXPRESSWAY": "EXPY",
    "FREEWAY": "FWY", "SUITE": "STE", "APARTMENT": "APT", "BUILDING": "BLDG",
    "FLOOR": "FL", "NORTH": "N", "SOUTH": "S", "EAST": "E", "WEST": "W",
    "NORTHEAST": "NE", "NORTHWEST": "NW", "SOUTHEAST": "SE", "SOUTHWEST": "SW",
}

def normalize_individual(first, middle, last) -> str:
    parts = [first] + ([middle] if middle else []) + [last]
    return base_normalize(" ".join(parts))

def normalize_entity(name: str) -> str:
    n = base_normalize(name)
    for phrase, abbrev in PHRASE_MAP:
        if n.endswith(" " + phrase):
            n = n[: -len(phrase)] + abbrev
            break
    toks = n.split(" ")
    if toks and toks[-1] in TOKEN_MAP:
        toks[-1] = TOKEN_MAP[toks[-1]]
    return " ".join(toks)

def normalize_address(addr: str) -> str:
    if not addr:
        return None
    return " ".join(ADDR_MAP.get(t, t) for t in base_normalize(addr).split(" "))

def norm_name_of(ev) -> str:
    if ev["partyType"] == "INDIVIDUAL":
        return normalize_individual(ev.get("firstName"), ev.get("middleName"), ev.get("lastName"))
    return normalize_entity(ev["entityName"])

def embed_text_of(ev) -> str:
    """Spec §2.3: text = normalized_name [+ ' ' + normalized_address]"""
    t = norm_name_of(ev)
    na = normalize_address(ev.get("address"))
    return f"{t} {na}" if na else t

# ------------------------------------------------------------ tier-4 mock LLM
def t4_verdict(inc_name, cand_name, inc_type, cand_type):
    """Faithful to spec §2.3 'Tier-4 mock LLM logic'."""
    if inc_type != cand_type:
        return "NO_MATCH", 0.0, "party types differ"
    a, b = inc_name, cand_name
    da, db = sorted(re.findall(r"\d+", a)), sorted(re.findall(r"\d+", b))
    if da != db:
        return "NO_MATCH", 0.0, "numeric name tokens differ; distinct registrations"
    if inc_type == "INDIVIDUAL" and a.split()[-1] != b.split()[-1]:
        return "NO_MATCH", 0.0, "last names differ"
    r = SequenceMatcher(None, a, b).ratio()
    if r >= T4_MATCH_RATIO:
        return "MATCH", r, ""
    if r <= T4_NO_MATCH_RATIO:
        return "NO_MATCH", r, ""
    return "UNCERTAIN", r, ""

# -------------------------------------------------------------------- corpus
BASE = datetime(2026, 5, 4, 9, 0, 0)
FIRST = ["James","Maria","Derek","Aisha","Thomas","Wei","Priya","Luis","Hannah","Omar",
         "Grace","Ivan","Noor","Peter","Lena","Marcus","Sofia","Kenji","Ruth","Andre",
         "Chloe","Rafael","Nadia","Victor","Elena","Samuel","Farah","Diego","Iris","Malik"]
LAST = ["Okonkwo","Vance","Delgado","Brennan","Nakamura","Whitfield","Osei","Kaminski",
        "Rahman","Ferraro","Lindqvist","Achebe","Moreau","Castellanos","Petrov","Hollis",
        "Bergstrom","Adeyemi","Novak","Quintero","Sandoval","Thorne","Ibrahim","Mercer"]
ENT_A = ["Cedar","Harbor","Summit","Ironwood","Blue Fern","Northgate","Stillwater","Kestrel",
         "Granite","Loma","Wexford","Ridgeline","Fairmont","Aspen","Torrey","Halcyon"]
ENT_B = ["Capital","Holdings","Residential","Partners","Equity","Properties","Ventures","Group"]
STREETS = ["Cedar Ridge Drive","Harbor Point Boulevard","Laurel Way","Fillmore Avenue",
           "Merchant Street","Kingsley Road","Thornton Lane","Belmont Court","Alder Place",
           "Sable Creek Drive","Winslow Avenue","Prescott Street","Dunmore Road","Verona Way"]
SOURCES = ["ORIGINATION", "SERVICING", "SURVEILLANCE"]

events = []
_eid = [0]

def mk(source, party_type, *, first=None, middle=None, last=None, entity=None,
       tin=None, address=None, role=None, loan=None, amount=None, day=0, note=None):
    _eid[0] += 1
    ev = {
        "eventId": f"EVT-{_eid[0]:05d}",
        "sourceSystem": source,
        "timestamp": (BASE + timedelta(days=day, minutes=_eid[0] % 480)).isoformat() + "Z",
        "partyType": party_type,
    }
    if party_type == "INDIVIDUAL":
        ev["firstName"] = first
        if middle: ev["middleName"] = middle
        ev["lastName"] = last
    else:
        ev["entityName"] = entity
    if tin: ev["ssnOrTaxId"] = tin
    if address: ev["address"] = address
    if role:
        ev["role"] = role
        ev["loanRef"] = loan
    if amount: ev["loanAmount"] = amount
    if note: ev["_note"] = note      # strip before POSTing if your validator is strict
    events.append(ev)
    return ev

# ---- THE DEMO CAST (must match the deck + script) --------------------------
ORANGE = "1209 Orange Street"
ORANGE_N = normalize_address(ORANGE)   # -> "1209 ORANGE ST"

# Patricia Morrison — the anchor you search on stage.
mk("ORIGINATION", "INDIVIDUAL", first="Patricia", last="Morrison",
   tin="412-88-7731", address=ORANGE, role="BORROWER", loan="MF-400001",
   amount=4_250_000, day=0, note="ANCHOR: the party you search live")
mk("ORIGINATION", "INDIVIDUAL", first="Patricia", last="Morrison",
   tin="412-88-7731", address=ORANGE, role="SPONSOR", loan="MF-400002",
   amount=2_900_000, day=2)

# ALPHA 100 LLC — the red-bordered (flagged) party on screen.
mk("ORIGINATION", "ENTITY", entity="Alpha 100 LLC", tin="47-1234567",
   address=ORANGE, role="BORROWER", loan="MF-400002", amount=2_900_000, day=1,
   note="FLAGGED: appears with red border in network view")

# R. Smith — co-party in the anchor's network.
mk("SERVICING", "INDIVIDUAL", first="Robert", last="Smith", tin="303-55-9182",
   address="88 Harbor Point Boulevard", role="GUARANTOR", loan="MF-400001", day=3)

# ---- SIGNAL 1: address fan-out at 1209 Orange St ---------------------------
# Needs >= FANOUT_MIN_PARTIES borrowers at one address inside FANOUT_WINDOW_DAYS.
for i, ent in enumerate(["Omega 55 LLC", "Bright Harbor Residential LLC", "Vantage Row LLC"]):
    mk("ORIGINATION", "ENTITY", entity=ent, tin=f"47-99{i:05d}", address=ORANGE,
       role="BORROWER", loan=f"MF-4001{i:02d}", amount=1_100_000 + i * 250_000,
       day=4 + i * 2, note="SIGNAL: address fan-out")

# ---- SIGNAL 2: shell cluster (one guarantor, co-located shells) ------------
SHELL_ADDR = "400 Merchant Street Suite 900"
for i, ent in enumerate(["Ridgeline SPV I LLC", "Ridgeline SPV II LLC", "Ridgeline SPV III LLC"]):
    mk("ORIGINATION", "ENTITY", entity=ent, tin=f"47-77{i:05d}", address=SHELL_ADDR,
       role="BORROWER", loan=f"MF-4002{i:02d}", amount=980_000, day=6 + i,
       note="SIGNAL: shell cluster")
    mk("ORIGINATION", "INDIVIDUAL", first="Gregory", last="Vance", tin="221-40-6655",
       address=SHELL_ADDR, role="GUARANTOR", loan=f"MF-4002{i:02d}", day=6 + i)

# ---- SIGNAL 3: circular roles (A sponsors B, B sponsors A) -----------------
mk("ORIGINATION", "INDIVIDUAL", first="Daniel", last="Ferraro", tin="509-22-3311",
   address="17 Alder Place", role="BORROWER", loan="MF-400301", amount=3_100_000, day=8)
mk("ORIGINATION", "INDIVIDUAL", first="Yusuf", last="Rahman", tin="617-31-8890",
   address="52 Belmont Court", role="SPONSOR", loan="MF-400301", day=8,
   note="SIGNAL: circular roles")
mk("ORIGINATION", "INDIVIDUAL", first="Yusuf", last="Rahman", tin="617-31-8890",
   address="52 Belmont Court", role="BORROWER", loan="MF-400302", amount=2_700_000, day=9)
mk("ORIGINATION", "INDIVIDUAL", first="Daniel", last="Ferraro", tin="509-22-3311",
   address="17 Alder Place", role="SPONSOR", loan="MF-400302", day=9)

# ---- SIGNAL 4: loan velocity (one party stacking loans in days) ------------
for i in range(4):
    mk("ORIGINATION", "ENTITY", entity="Torrey Equity Group LLC", tin="47-5550001",
       address="900 Fillmore Avenue", role="BORROWER", loan=f"MF-4004{i:02d}",
       amount=1_800_000 + i * 90_000, day=10 + i,
       note="SIGNAL: loan velocity")

# ---- VOLUME FILLER --------------------------------------------------------
# A fixed party pool with repeat borrowers — a real portfolio has more loans
# than parties. Targets the counts the spoken script quotes.
TARGET_FILLER_PARTIES = 330
TARGET_FILLER_LOANS = 290

pool = []
_used_names = set()
while len(pool) < TARGET_FILLER_PARTIES:
    addr = f"{random.randint(100,9800)} {random.choice(STREETS)}"
    if random.random() < 0.55:
        f_, l_ = random.choice(FIRST), random.choice(LAST)
        key = ("INDIVIDUAL", f"{f_} {l_}")
        if key in _used_names:
            continue
        _used_names.add(key)
        pool.append(dict(party_type="INDIVIDUAL", first=f_, last=l_, address=addr,
                         tin=f"{random.randint(100,899)}-{random.randint(10,99)}-{random.randint(1000,9999)}"))
    else:
        ent = f"{random.choice(ENT_A)} {random.choice(ENT_B)} LLC"
        key = ("ENTITY", ent)
        if key in _used_names:
            continue
        _used_names.add(key)
        pool.append(dict(party_type="ENTITY", entity=ent, address=addr,
                         tin=f"47-{random.randint(1000000,9999999)}"))

def emit_pool(p, *, role, loan, amount=None, day):
    return mk(random.choice(SOURCES), p["party_type"],
              first=p.get("first"), last=p.get("last"), entity=p.get("entity"),
              tin=p["tin"], address=p["address"], role=role, loan=loan,
              amount=amount, day=day)

loan_no = 401000
for i in range(TARGET_FILLER_LOANS):
    day = random.randint(0, 60)
    loan = f"MF-{loan_no}"; loan_no += 1
    borrower = random.choice(pool)
    emit_pool(borrower, role="BORROWER", loan=loan,
              amount=random.randrange(750_000, 12_000_000, 50_000), day=day)
    if random.random() < 0.55:
        co = random.choice(pool)
        if co is not borrower:
            emit_pool(co, role=random.choice(["SPONSOR", "GUARANTOR"]), loan=loan, day=day)

# =====================================================================
# THE SIX LIVE RESOLUTION CASES — one per tier, plus two refusals
# =====================================================================
demo = []

def dm(label, expect, why, **kw):
    ev = mk(**kw)
    events.pop()                     # live cases are NOT part of the seed corpus
    _eid[0] -= 1
    ev["eventId"] = f"DEMO-{len(demo)+1:02d}"
    demo.append({"label": label, "expect": expect, "why": why, "event": ev})
    return ev

dm("T1 — exact identifier", "T1", "same ssnOrTaxId + same partyType; name spelling irrelevant",
   source="SERVICING", party_type="ENTITY", entity="ALPHA 100 L.L.C.",
   tin="47-1234567", address="1209 Orange St", role="BORROWER", loan="MF-400002", day=20)

dm("T2 — normalized name + address", "T2", "normalizes to same name AND same address as the anchor",
   source="SURVEILLANCE", party_type="INDIVIDUAL", first="Patricia", last="Morrison",
   address="1209 Orange Street", role="SPONSOR", loan="MF-400002", day=21)

dm("T3 — vector auto-match", "T3", "same name, address recorded WITH the suite -> different Property, so T2 misses; vector catches",
   source="SERVICING", party_type="INDIVIDUAL", first="Patricia", last="Morrison",
   address="1209 Orange Street Suite 300", role="GUARANTOR", loan="MF-401004", day=22)

dm("T4 — AI disambiguation", "T4", "nickname: score high but name differs -> T3 defers, T4 judges",
   source="SURVEILLANCE", party_type="INDIVIDUAL", first="Pat", last="Morrison",
   address="1209 Orange Street", role="SPONSOR", loan="MF-400105", day=23)

dm("REFUSAL — numeric guard", "NEW PARTY", "Alpha 100 vs Alpha 200: numeric tokens differ -> hard NO_MATCH",
   source="ORIGINATION", party_type="ENTITY", entity="Alpha 200 LLC", tin="47-6000001",
   address="1209 Orange Street", role="BORROWER", loan="MF-400106", amount=1_400_000, day=24)

# NOTE: a "party type guard" case is NOT included. T3 queries the vector index
# filtered by partyType, so an INDIVIDUAL and an ENTITY are never in the same
# candidate pool — T4's "party types differ" branch is unreachable in practice.
# The partition is real, but it happens silently at the index. Nothing to show.
#
# This case instead exercises the last-name guard, which IS reachable — and is a
# known false negative. Demo it only if you want to own the limitation out loud.
dm("REFUSAL — last-name guard", "NEW PARTY", "surname typo: vector score very high, but last-name guard refuses -> duplicate, not a bad merge",
   source="SURVEILLANCE", party_type="INDIVIDUAL", first="Patricia", last="Morrisson",
   address="1209 Orange Street", role="SPONSOR", loan="MF-400108", day=25)

# ============================================================ embeddings + calibration
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="./data")
    ap.add_argument("--model", default="sentence-transformers/all-MiniLM-L6-v2")
    ap.add_argument("--no-embed", action="store_true", help="skip embedding (structure only)")
    args = ap.parse_args()
    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)

    (out / "seed_events.json").write_text(json.dumps(events, indent=2))
    (out / "demo_events.json").write_text(json.dumps(demo, indent=2))

    parties = {(e["partyType"], norm_name_of(e)) for e in events}
    loans = {e["loanRef"] for e in events if e.get("loanRef")}
    print(f"seed events : {len(events)}")
    print(f"distinct parties (pre-resolution): {len(parties)}")
    print(f"distinct loans: {len(loans)}")
    print(f"demo cases  : {len(demo)}\n")

    if args.no_embed:
        print("--no-embed: skipping embeddings and T3 calibration."); return

    from sentence_transformers import SentenceTransformer
    import numpy as np
    m = SentenceTransformer(args.model)

    texts = sorted({embed_text_of(e) for e in events} | {embed_text_of(d["event"]) for d in demo})
    vecs = m.encode(texts, normalize_embeddings=True, batch_size=64, show_progress_bar=True)
    table = {t: [round(float(x), 6) for x in v] for t, v in zip(texts, vecs)}
    (out / "embeddings.json").write_text(json.dumps(table))
    print(f"\nembeddings  : {len(table)} texts x {len(vecs[0])} dims -> {out/'embeddings.json'}")

    # ---- calibration: what tier will each demo case ACTUALLY hit? ----
    idx = {t: np.array(v) for t, v in zip(texts, vecs)}
    seed_by_type = {}
    for e in events:
        seed_by_type.setdefault(e["partyType"], []).append(e)

    lines = ["# PNI demo calibration", "",
             f"auto_match {AUTO_MATCH_THRESHOLD} (cosine {COS_AUTO:.2f}) · "
             f"no_match {NO_MATCH_THRESHOLD} (cosine {COS_NOMATCH:.2f}) · "
             f"T4 MATCH ratio >= {T4_MATCH_RATIO}", ""]
    print("\n" + "=" * 92)
    print(f"{'case':<28}{'expect':<12}{'top score':>10}{'name==':>8}  actual")
    print("=" * 92)

    for d in demo:
        ev = d["event"]
        et, nn = embed_text_of(ev), norm_name_of(ev)
        q = idx[et]
        best, best_s, best_nn = None, -1, None
        for c in seed_by_type.get(ev["partyType"], []):
            ct, cnn = embed_text_of(c), norm_name_of(c)
            if ct == et and cnn == nn and c is ev:
                continue
            s = (1 + float(np.dot(q, idx[ct]))) / 2
            if s > best_s:
                best, best_s, best_nn = c, s, cnn
        # tier simulation
        if ev.get("ssnOrTaxId") and any(
                c.get("ssnOrTaxId") == ev["ssnOrTaxId"] and c["partyType"] == ev["partyType"]
                for c in events):
            actual = "T1 exact_identifier"
        elif normalize_address(ev.get("address")) and any(
                norm_name_of(c) == nn and c["partyType"] == ev["partyType"]
                and normalize_address(c.get("address")) == normalize_address(ev.get("address"))
                for c in events):
            actual = "T2 normalized_name_address"
        elif best_s < NO_MATCH_THRESHOLD:
            actual = "NEW PARTY (below no_match)"
        elif best_s >= AUTO_MATCH_THRESHOLD and best_nn == nn:
            actual = f"T3 vector ({best_s:.3f})"
        else:
            v, r, why = t4_verdict(nn, best_nn, ev["partyType"], best["partyType"])
            actual = f"T4 {v}" + (f" (ratio {r:.3f})" if r else f" ({why})")
            if v != "MATCH":
                actual += " -> NEW PARTY"
        ok = "OK " if d["expect"].split()[0] in actual else "!! "
        print(f"{ok}{d['label']:<26}{d['expect']:<12}{best_s:>10.3f}{str(best_nn==nn):>8}  {actual}")
        lines.append(f"- **{d['label']}** — expect `{d['expect']}`, actual `{actual}`, "
                     f"top score {best_s:.3f} vs `{best_nn}`")

    print("=" * 92)
    print("!! = the pipeline will NOT do what the script says. Fix the data, not the demo.")
    (out / "calibration.md").write_text("\n".join(lines) + "\n")

if __name__ == "__main__":
    main()
