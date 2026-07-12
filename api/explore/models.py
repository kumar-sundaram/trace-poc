"""Explore response contract (FR-13, FR-14, FR-15)."""

from typing import Literal

from pydantic import BaseModel

NodeType = Literal["Party", "Property", "Loan"]


class ExploreNode(BaseModel):
    id: str
    nodeType: NodeType
    label: str
    hop: int
    properties: dict


class ExploreEdge(BaseModel):
    source: str  # always the Party end
    target: str
    type: Literal["CONNECTED_TO", "HAS_ROLE_ON"]
    role: str | None = None
    tier: str | None = None
    edgeSource: str | None = None  # the FR-11 'source' property
    sourceSystem: str | None = None
    eventId: str | None = None


class GuardMarker(BaseModel):
    """FR-14: a node too connected to expand — summary instead of paths."""

    nodeId: str
    nodeType: NodeType
    label: str
    degree: int
    expanded: Literal[False] = False


class SignalFlag(BaseModel):
    """FR-15: flag reference only — signal id and pattern type, no detail."""

    partyId: str
    signalId: str
    patternType: str


class ExploreResult(BaseModel):
    anchor: ExploreNode
    nodes: list[ExploreNode]
    edges: list[ExploreEdge]
    guards: list[GuardMarker]
    flags: list[SignalFlag]
