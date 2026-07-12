"""Signal endpoints: list raised signals; admin full-graph re-run (FR-18)."""

from fastapi import APIRouter, Request
from pydantic import BaseModel

router = APIRouter(tags=["signal"])


class SignalView(BaseModel):
    id: str
    patternType: str
    severity: str
    status: str
    relatedPartyIds: list[str]
    evidencePath: list[str]
    attributeId: str
    causationEventId: str
    raisedAt: str


@router.get("/signals", response_model=list[SignalView])
def list_signals(request: Request) -> list[SignalView]:
    graph = request.app.state.graph
    records = graph.execute_read(
        lambda tx: [
            dict(r)
            for r in tx.run(
                "MATCH (s:Signal {status: 'RAISED'}) "
                "RETURN s.id AS id, s.patternType AS patternType, "
                "s.severity AS severity, s.status AS status, "
                "s.relatedPartyIds AS relatedPartyIds, s.evidencePath AS evidencePath, "
                "s.attributeId AS attributeId, s.causationEventId AS causationEventId, "
                "toString(s.raisedAt) AS raisedAt "
                "ORDER BY s.raisedAt DESC"
            )
        ]
    )
    return [SignalView(**record) for record in records]


@router.post("/admin/signals/rerun")
def rerun_rules(request: Request) -> dict:
    """FR-18: on-demand rule evaluation against the full graph."""
    return request.app.state.signals.evaluate_all()
