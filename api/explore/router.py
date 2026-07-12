"""Explore REST endpoint (FR-13)."""

from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request

from api.explore.models import ExploreResult

router = APIRouter(tags=["explore"])


@router.get("/explore", response_model=ExploreResult)
def explore(
    request: Request,
    anchorType: Literal["party", "loan", "property"] = Query(
        description="What the anchor identifies"
    ),
    q: str = Query(min_length=1, description="Party id or name, loanRef, or address"),
) -> ExploreResult:
    result = request.app.state.explore.explore(anchorType, q)
    if result is None:
        raise HTTPException(status_code=404, detail=f"no {anchorType} found for {q!r}")
    return result
