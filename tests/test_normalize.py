"""FR-4 normalization, driven by the curated seed scenarios."""

from api.normalize import (
    normalize_address,
    normalize_entity_name,
    normalize_individual_name,
    normalize_name,
)


class TestIndividualNames:
    def test_case_insensitive_cluster(self):
        # T2_VARIANT_CLUSTER: Jonathan Smith vs JONATHAN SMITH must be Tier-2 equal
        assert normalize_individual_name("Jonathan", "Smith") == normalize_individual_name(
            "JONATHAN", "SMITH"
        )

    def test_middle_initial_variant_stays_distinct(self):
        # "Jon A. Smith" must NOT normalize to "Jonathan Smith" — it resolves via
        # Tier 3 instead (§8 step 2 allows "Tier 2/3").
        assert normalize_individual_name("Jon A.", "Smith") == "JON A SMITH"
        assert normalize_individual_name("Jon A.", "Smith") != normalize_individual_name(
            "Jonathan", "Smith"
        )

    def test_punctuation_stripped(self):
        # TIER1_SSN_MATCH pair: Tier-One vs Tierone
        assert normalize_individual_name("Jon", "Tier-One") == "JON TIERONE"

    def test_whitespace_collapsed(self):
        assert normalize_individual_name("  Elena ", "  Novak  ") == "ELENA NOVAK"


class TestEntityNames:
    def test_llc_suffix_forms_equal(self):
        # T2_ENTITY_SUFFIX: Meridian Multifamily Holdings LLC vs "…, L.L.C."
        assert normalize_entity_name("Meridian Multifamily Holdings LLC") == normalize_entity_name(
            "Meridian Multifamily Holdings, L.L.C."
        )

    def test_long_form_llc(self):
        assert (
            normalize_entity_name("Meridian Multifamily Holdings Limited Liability Company")
            == "MERIDIAN MULTIFAMILY HOLDINGS LLC"
        )

    def test_inc_forms_equal(self):
        assert normalize_entity_name("Acme Incorporated") == normalize_entity_name("Acme, Inc.")

    def test_corp_and_ltd(self):
        assert normalize_entity_name("Zenith Corporation") == "ZENITH CORP"
        assert normalize_entity_name("Zenith Limited") == "ZENITH LTD"

    def test_suffix_only_at_end(self):
        # "Limited" inside the name must not be rewritten
        assert normalize_entity_name("Limited Editions Gallery LLC") == "LIMITED EDITIONS GALLERY LLC"


class TestNormalizeNameDispatch:
    def test_individual_dispatch(self):
        assert normalize_name("INDIVIDUAL", first_name="Jon", last_name="Smith") == "JON SMITH"

    def test_entity_dispatch(self):
        assert normalize_name("ENTITY", entity_name="Apex Property Management") == (
            "APEX PROPERTY MANAGEMENT"
        )


class TestAddresses:
    def test_street_type_abbreviated(self):
        assert normalize_address("123 Main Street, Atlanta, GA 30303") == normalize_address(
            "123 Main St Atlanta GA 30303"
        )

    def test_curated_seed_address(self):
        assert normalize_address("123 Main St, Atlanta, GA 30303") == "123 MAIN ST ATLANTA GA 30303"

    def test_unit_and_directional(self):
        assert (
            normalize_address("53329 Collins Drive Apartment 431, West Underwoodville")
            == "53329 COLLINS DR APT 431 W UNDERWOODVILLE"
        )

    def test_idempotent(self):
        once = normalize_address("777 Risk Avenue, Las Vegas, NV 89109")
        assert normalize_address(once) == once
