"""Ingestion REST endpoint (FR-1, FR-2, FR-8)."""

from fastapi import APIRouter, Request, status

from api.ingestion.models import AcceptResponse, CorrelationRef, PartyEvent

router = APIRouter(tags=["ingestion"])


@router.post(
    "/events",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=AcceptResponse,
)
def accept_event(event: PartyEvent, request: Request) -> AcceptResponse:
    """Accept a source-tagged party event.

    Contract violations never reach here — Pydantic rejects them with 422
    and no partial processing (FR-8). Re-delivery of an already-processed
    (sourceSystem, eventId) pair is acknowledged but not reprocessed (FR-2).
    """
    resolution = request.app.state.resolution
    duplicate = resolution.is_already_processed(event)
    if not duplicate:
        resolution.resolve(event)
    return AcceptResponse(
        status="accepted",
        duplicate=duplicate,
        correlation=CorrelationRef(sourceSystem=event.sourceSystem, eventId=event.eventId),
    )
