"""Admin endpoints: demo reset (FR-24)."""

from fastapi import APIRouter, Request

router = APIRouter(tags=["admin"])


@router.post("/admin/reset")
def reset(request: Request) -> dict:
    """Clear the graph and both event streams, reload the synthetic seed."""
    return request.app.state.seeder.reset()
