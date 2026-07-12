"""Party-type-aware normalization (FR-4).

Individuals: uppercase, punctuation-stripped, whitespace-collapsed full name.
Entities: the same plus legal-suffix normalization (L.L.C. → LLC, Incorporated → INC, …).
Addresses: the same plus USPS-style street-type/unit/directional abbreviation.

These rules are spec-defined behavior (FR-4), not tuning knobs, so the maps
live here rather than in settings.
"""

import re

_PUNCTUATION = re.compile(r"[^\w\s]", re.UNICODE)
_WHITESPACE = re.compile(r"\s+")

# Multi-word forms first — they are collapsed before single-token mapping.
_ENTITY_SUFFIX_PHRASES: tuple[tuple[str, str], ...] = (
    ("LIMITED LIABILITY COMPANY", "LLC"),
    ("LIMITED LIABILITY PARTNERSHIP", "LLP"),
    ("LIMITED PARTNERSHIP", "LP"),
)

_ENTITY_SUFFIX_TOKENS: dict[str, str] = {
    "LLC": "LLC",
    "LLP": "LLP",
    "LP": "LP",
    "INCORPORATED": "INC",
    "INC": "INC",
    "CORPORATION": "CORP",
    "CORP": "CORP",
    "COMPANY": "CO",
    "CO": "CO",
    "LIMITED": "LTD",
    "LTD": "LTD",
}

# USPS Publication 28 style abbreviations (stretch goal in FR-4, in scope).
_ADDRESS_TOKENS: dict[str, str] = {
    "STREET": "ST",
    "AVENUE": "AVE",
    "BOULEVARD": "BLVD",
    "DRIVE": "DR",
    "LANE": "LN",
    "ROAD": "RD",
    "COURT": "CT",
    "PLACE": "PL",
    "PLAZA": "PLZ",
    "POINT": "PT",
    "PARKWAY": "PKWY",
    "HIGHWAY": "HWY",
    "CIRCLE": "CIR",
    "TERRACE": "TER",
    "TRAIL": "TRL",
    "SQUARE": "SQ",
    "EXPRESSWAY": "EXPY",
    "FREEWAY": "FWY",
    "SUITE": "STE",
    "APARTMENT": "APT",
    "BUILDING": "BLDG",
    "FLOOR": "FL",
    "NORTH": "N",
    "SOUTH": "S",
    "EAST": "E",
    "WEST": "W",
    "NORTHEAST": "NE",
    "NORTHWEST": "NW",
    "SOUTHEAST": "SE",
    "SOUTHWEST": "SW",
}


def _base_normalize(text: str) -> str:
    """Uppercase, strip punctuation, collapse whitespace."""
    text = _PUNCTUATION.sub("", text.upper())
    return _WHITESPACE.sub(" ", text).strip()


def normalize_individual_name(first_name: str, last_name: str) -> str:
    return _base_normalize(f"{first_name} {last_name}")


def normalize_entity_name(entity_name: str) -> str:
    name = _base_normalize(entity_name)
    for phrase, abbrev in _ENTITY_SUFFIX_PHRASES:
        if name.endswith(" " + phrase):
            name = name[: -len(phrase)] + abbrev
            break
    tokens = name.split(" ")
    if len(tokens) > 1 and tokens[-1] in _ENTITY_SUFFIX_TOKENS:
        tokens[-1] = _ENTITY_SUFFIX_TOKENS[tokens[-1]]
    return " ".join(tokens)


def normalize_name(
    party_type: str,
    *,
    first_name: str | None = None,
    last_name: str | None = None,
    entity_name: str | None = None,
) -> str:
    if party_type == "INDIVIDUAL":
        return normalize_individual_name(first_name or "", last_name or "")
    return normalize_entity_name(entity_name or "")


def normalize_address(address: str) -> str:
    tokens = _base_normalize(address).split(" ")
    return " ".join(_ADDRESS_TOKENS.get(token, token) for token in tokens if token)
