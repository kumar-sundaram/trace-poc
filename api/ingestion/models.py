"""Ingestion request contract (FR-1) — a §9 deliverable.

Validation here is the synchronous 4xx gate of FR-8: a request that violates
the contract is rejected whole, with no partial processing.
"""

from pydantic import BaseModel, ConfigDict, field_validator, model_validator
from typing import Literal

from api.config import get_settings
from api.normalize import normalize_address, normalize_name


class PartyEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sourceSystem: str
    eventId: str
    partyType: Literal["INDIVIDUAL", "ENTITY"]
    firstName: str | None = None
    lastName: str | None = None
    entityName: str | None = None
    address: str | None = None
    ssnOrTaxId: str | None = None
    role: str | None = None
    loanRef: str | None = None

    @field_validator(
        "firstName", "lastName", "entityName", "address", "ssnOrTaxId", "role", "loanRef",
        mode="before",
    )
    @classmethod
    def blank_is_absent(cls, value):
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @model_validator(mode="after")
    def enforce_contract(self) -> "PartyEvent":
        settings = get_settings()
        if self.partyType == "INDIVIDUAL":
            if not (self.firstName and self.lastName):
                raise ValueError("INDIVIDUAL requires firstName and lastName")
        else:
            if not self.entityName:
                raise ValueError("ENTITY requires entityName")
        if self.sourceSystem not in settings.known_source_systems:
            raise ValueError(f"unknown sourceSystem {self.sourceSystem!r}")
        if self.role is not None:
            if self.role not in settings.role_vocabulary:
                raise ValueError(f"role {self.role!r} not in configured vocabulary")
            if not self.loanRef:
                raise ValueError("loanRef is required when role is present")
        # §4.1: name + address is the minimum resolution basis for borrowers;
        # the pipeline must never receive a borrower without an address.
        if self.role == "BORROWER" and not self.address:
            raise ValueError("address is required for BORROWER role")
        return self

    @property
    def normalized_name(self) -> str:
        return normalize_name(
            self.partyType,
            first_name=self.firstName,
            last_name=self.lastName,
            entity_name=self.entityName,
        )

    @property
    def normalized_address(self) -> str | None:
        return normalize_address(self.address) if self.address else None

    @property
    def raw_record_id(self) -> str:
        """Deterministic identity for the (sourceSystem, eventId) pair (FR-2)."""
        return f"{self.sourceSystem}:{self.eventId}"


class CorrelationRef(BaseModel):
    sourceSystem: str
    eventId: str


class AcceptResponse(BaseModel):
    """FR-8: acknowledgement only — resolution outcomes are published as
    events (FR-20), never returned here."""

    status: Literal["accepted"]
    duplicate: bool
    correlation: CorrelationRef
