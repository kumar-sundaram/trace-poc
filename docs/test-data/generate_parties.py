import csv
import uuid
import random
from pathlib import Path

from faker import Faker

fake = Faker()
random.seed(42)
Faker.seed(42)

# Configuration
DATA_DIR = Path(__file__).resolve().parent
SCALE_RECORDS = 100_000
CURATED_FILE = DATA_DIR / "party_network_seed_curated.csv"
NEGATIVE_FILE = DATA_DIR / "party_network_negative.csv"
SCALE_FILE = DATA_DIR / "party_network_scale_100k.csv"

SOURCES = ["LoanSphere_Origination", "ServicingMaster_Pro", "Core_Invest_DB"]
POC_ROLES = ["BORROWER", "KEY_BORROWER_PRINCIPAL", "SPONSOR"]
EXTENDED_ROLES = POC_ROLES + ["PROPERTY_MANAGER", "GUARANTOR"]
HEADERS = [
    "scenario",
    "sourceSystem",
    "eventId",
    "partyType",
    "firstName",
    "lastName",
    "entityName",
    "address",
    "ssnOrTaxId",
    "role",
    "loanRef",
]


def create_base_event(source=None, party_type=None, role=None, loan_ref=None):
    return {
        "scenario": "",
        "sourceSystem": source or random.choice(SOURCES),
        "eventId": str(uuid.uuid4()),
        "partyType": party_type or random.choice(["INDIVIDUAL", "ENTITY"]),
        "firstName": "",
        "lastName": "",
        "entityName": "",
        "address": fake.address().replace("\n", ", "),
        "ssnOrTaxId": fake.ssn() if random.random() > 0.2 else "",
        "role": role or random.choice(EXTENDED_ROLES),
        "loanRef": loan_ref or f"MF-{random.randint(100000, 999999)}",
    }


def curated_record(scenario, **overrides):
    role = overrides.get("role")
    record = create_base_event(
        source=overrides.get("sourceSystem"),
        party_type=overrides.get("partyType"),
        role=role,
        loan_ref=overrides.get("loanRef"),
    )
    record["scenario"] = scenario
    record.update(overrides)
    if "ssnOrTaxId" not in overrides:
        record["ssnOrTaxId"] = ""
    return record


def build_curated_records():
    records = []
    smith_address = "123 Main St, Atlanta, GA 30303"
    smith_idempotent_event = str(uuid.uuid4())
    smith_borrower_payload = {
        "sourceSystem": "LoanSphere_Origination",
        "partyType": "INDIVIDUAL",
        "role": "BORROWER",
        "eventId": smith_idempotent_event,
        "firstName": "Jonathan",
        "lastName": "Smith",
        "address": smith_address,
        "ssnOrTaxId": "",
        "loanRef": "MF-111111",
    }

    # FR-25a / §8 step 2: Tier 2 cluster — 3+ name variants → one party
    records.append(curated_record("T2_VARIANT_CLUSTER", **smith_borrower_payload))
    # FR-25h / §8 step 5: idempotent re-delivery (byte-identical payload)
    records.append(curated_record("IDEMPOTENCY_DUPLICATE", **smith_borrower_payload))
    records.append(
        curated_record(
            "T2_VARIANT_CLUSTER",
            sourceSystem="ServicingMaster_Pro",
            partyType="INDIVIDUAL",
            role="SPONSOR",
            firstName="JONATHAN",
            lastName="SMITH",
            address=smith_address,
            loanRef="MF-222222",
        )
    )
    records.append(
        curated_record(
            "T2_VARIANT_CLUSTER",
            sourceSystem="Core_Invest_DB",
            partyType="INDIVIDUAL",
            role="BORROWER",
            firstName="Jon A.",
            lastName="Smith",
            address=smith_address,
            loanRef="MF-333333",
        )
    )

    # FR-25d / §8 step 4: cross-source multi-role aggregation on Jonathan Smith cluster (above)

    # FR-25c: entity legal-suffix normalization
    meridian_address = "4500 Peak Blvd, Denver, CO 80202"
    records.append(
        curated_record(
            "T2_ENTITY_SUFFIX",
            sourceSystem="LoanSphere_Origination",
            partyType="ENTITY",
            role="BORROWER",
            entityName="Meridian Multifamily Holdings LLC",
            address=meridian_address,
            loanRef="MF-211111",
        )
    )
    records.append(
        curated_record(
            "T2_ENTITY_SUFFIX",
            sourceSystem="Core_Invest_DB",
            partyType="ENTITY",
            role="GUARANTOR",
            entityName="Meridian Multifamily Holdings, L.L.C.",
            address=meridian_address,
            loanRef="MF-211112",
        )
    )

    # FR-3: Tier 1 deterministic SSN match
    tier1_ssn = "900-11-2233"
    records.append(
        curated_record(
            "TIER1_SSN_MATCH",
            sourceSystem="LoanSphere_Origination",
            partyType="INDIVIDUAL",
            role="BORROWER",
            firstName="John",
            lastName="Tierone",
            address="100 First Ave, Boston, MA 02108",
            ssnOrTaxId=tier1_ssn,
            loanRef="MF-311111",
        )
    )
    records.append(
        curated_record(
            "TIER1_SSN_MATCH",
            sourceSystem="ServicingMaster_Pro",
            partyType="INDIVIDUAL",
            role="SPONSOR",
            firstName="Jon",
            lastName="Tier-One",
            address="200 Second Ave, Boston, MA 02109",
            ssnOrTaxId=tier1_ssn,
            loanRef="MF-311112",
        )
    )

    # FR-25b: Tier 3/4 fuzzy pair with differing address
    records.append(
        curated_record(
            "T3_T4_FUZZY",
            sourceSystem="LoanSphere_Origination",
            partyType="INDIVIDUAL",
            role="BORROWER",
            firstName="Robert",
            lastName="Chen",
            address="88 Birch Ln, Austin, TX 78701",
            loanRef="MF-411111",
        )
    )
    records.append(
        curated_record(
            "T3_T4_FUZZY",
            sourceSystem="ServicingMaster_Pro",
            partyType="INDIVIDUAL",
            role="SPONSOR",
            firstName="Robb",
            lastName="Chen",
            address="412 Congress Ave, Austin, TX 78701",
            loanRef="MF-411112",
        )
    )

    # FR-5: address-less non-borrower — confidence must be capped
    records.append(
        curated_record(
            "ADDRESS_LESS_CONFIDENCE",
            sourceSystem="ServicingMaster_Pro",
            partyType="INDIVIDUAL",
            role="SPONSOR",
            firstName="Elena",
            lastName="Novak",
            address="",
            loanRef="MF-511111",
        )
    )

    # Party-type isolation — similar names must not merge across types
    records.append(
        curated_record(
            "PARTY_TYPE_ISOLATION",
            sourceSystem="LoanSphere_Origination",
            partyType="ENTITY",
            role="BORROWER",
            entityName="River Oaks Holdings LLC",
            address="700 River Oaks Blvd, Houston, TX 77019",
            loanRef="MF-611111",
        )
    )
    records.append(
        curated_record(
            "PARTY_TYPE_ISOLATION",
            sourceSystem="Core_Invest_DB",
            partyType="INDIVIDUAL",
            role="SPONSOR",
            firstName="River",
            lastName="Oaks",
            address="701 River Oaks Blvd, Houston, TX 77019",
            loanRef="MF-611112",
        )
    )

    # Multi-source entity exposure (supplementary cross-system case)
    apex_address = "900 Skyline Dr, Seattle, WA 98101"
    records.append(
        curated_record(
            "MULTI_SOURCE_ENTITY_EXPOSURE",
            sourceSystem="Core_Invest_DB",
            partyType="ENTITY",
            role="PROPERTY_MANAGER",
            entityName="Apex Property Management",
            address=apex_address,
            loanRef="MF-711111",
        )
    )
    records.append(
        curated_record(
            "MULTI_SOURCE_ENTITY_EXPOSURE",
            sourceSystem="LoanSphere_Origination",
            partyType="ENTITY",
            role="SPONSOR",
            entityName="Apex Property Management",
            address=apex_address,
            loanRef="MF-711112",
        )
    )

    # FR-25e / §8 step 6: legitimate high-connectivity party — must NOT fan-out
    patricia_addresses = [
        "2100 Lakeview Pkwy, Chicago, IL 60601",
        "4550 Michigan Ave, Chicago, IL 60611",
        "8900 Sheridan Rd, Evanston, IL 60201",
        "1200 W Madison St, Chicago, IL 60607",
        "3300 Belmont Ave, Chicago, IL 60618",
        "5500 S Shore Dr, Chicago, IL 60637",
    ]
    patricia_roles = [
        ("LoanSphere_Origination", "BORROWER", "MF-400001"),
        ("LoanSphere_Origination", "KEY_BORROWER_PRINCIPAL", "MF-400002"),
        ("ServicingMaster_Pro", "BORROWER", "MF-400003"),
        ("ServicingMaster_Pro", "SPONSOR", "MF-400004"),
        ("Core_Invest_DB", "SPONSOR", "MF-400005"),
        ("Core_Invest_DB", "BORROWER", "MF-400006"),
    ]
    for idx, (source, role, loan_ref) in enumerate(patricia_roles):
        records.append(
            curated_record(
                "HIGH_CONNECTIVITY_NEGATIVE",
                sourceSystem=source,
                partyType="INDIVIDUAL",
                role=role,
                firstName="Patricia",
                lastName="Morrison",
                address=patricia_addresses[idx],
                loanRef=loan_ref,
            )
        )

    # FR-25f / §8 step 7: planted fan-out — must fire signal
    fanout_address = "777 Risk Avenue, Las Vegas, NV 89109"
    for entity_name, loan_ref in [
        ("Alpha 100 LLC", "MF-811111"),
        ("Beta 200 LLC", "MF-811112"),
        ("Gamma 300 LLC", "MF-811113"),
    ]:
        records.append(
            curated_record(
                "FANOUT_POSITIVE",
                sourceSystem="LoanSphere_Origination",
                partyType="ENTITY",
                role="BORROWER",
                entityName=entity_name,
                address=fanout_address,
                loanRef=loan_ref,
            )
        )

    # FR-25g / §8 step 8: high-degree common attribute excluded by degree guard
    degree_guard_address = "Corporation Trust Center, 1209 Orange St, Wilmington, DE 19801"
    for i in range(250):
        records.append(
            curated_record(
                "DEGREE_GUARD",
                sourceSystem="Core_Invest_DB",
                partyType="ENTITY",
                role="BORROWER",
                entityName=f"Generic Holdings {i} LLC",
                address=degree_guard_address,
                loanRef=f"MF-9{i:05d}",
            )
        )

    return records


def build_negative_records():
    """Contract-violation rows for synchronous 4xx validation tests (§8 step 3)."""
    return [
        curated_record(
            "VALIDATION_REJECT_BORROWER_NO_ADDRESS",
            sourceSystem="LoanSphere_Origination",
            partyType="INDIVIDUAL",
            role="BORROWER",
            firstName="Alex",
            lastName="Noaddress",
            address="",
            loanRef="MF-ERR001",
        ),
        curated_record(
            "VALIDATION_REJECT_INDIVIDUAL_MISSING_NAME",
            sourceSystem="LoanSphere_Origination",
            partyType="INDIVIDUAL",
            role="SPONSOR",
            firstName="",
            lastName="",
            address="500 Error Ln, Portland, OR 97201",
            loanRef="MF-ERR002",
        ),
        curated_record(
            "VALIDATION_REJECT_ENTITY_MISSING_NAME",
            sourceSystem="Core_Invest_DB",
            partyType="ENTITY",
            role="GUARANTOR",
            entityName="",
            address="600 Error Ln, Portland, OR 97202",
            loanRef="MF-ERR003",
        ),
    ]


def build_scale_records(count):
    """NFR-7 bulk probe — synthetic background only, no curated scenarios."""
    records = []
    for i in range(count):
        event = create_base_event()
        event["scenario"] = "SCALE_BULK"
        event["loanRef"] = f"MF-{100000 + i}"

        if event["partyType"] == "INDIVIDUAL":
            event["firstName"] = fake.first_name()
            event["lastName"] = fake.last_name()
        else:
            prefixes = ["Summit", "Pinnacle", "Oak", "River", "Urban", "Metro", "Crescent", "Vista"]
            suffixes = ["Holdings LLC", "Properties LLC", "Real Estate LP", "Capital Group", "Multifamily LLC"]
            event["entityName"] = f"{random.choice(prefixes)} {fake.word().capitalize()} {random.choice(suffixes)}"

        records.append(event)

    random.shuffle(records)
    return records


def write_csv(path, records):
    with open(path, mode="w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=HEADERS)
        writer.writeheader()
        writer.writerows(records)


def summarize(records):
    counts = {}
    for record in records:
        counts[record["scenario"]] = counts.get(record["scenario"], 0) + 1
    return counts


def main():
    curated = build_curated_records()
    negative = build_negative_records()
    scale = build_scale_records(SCALE_RECORDS)

    write_csv(CURATED_FILE, curated)
    write_csv(NEGATIVE_FILE, negative)
    write_csv(SCALE_FILE, scale)

    print(f"Wrote {len(curated)} curated records to {CURATED_FILE}")
    print(f"Wrote {len(negative)} negative records to {NEGATIVE_FILE}")
    print(f"Wrote {len(scale)} scale records to {SCALE_FILE}")
    print("\nCurated scenario counts:")
    for scenario, count in sorted(summarize(curated).items()):
        print(f"  {scenario}: {count}")


if __name__ == "__main__":
    main()
