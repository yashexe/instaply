"""Discovery API router."""

import aiosqlite
from fastapi import APIRouter, Depends, HTTPException, Query

from src.db.connection import get_db
from src.discovery import repository, service
from src.discovery.models import DiscoveryRunStats, SuggestionResponse

router = APIRouter(prefix="/api/discovery", tags=["discovery"])

DEFAULT_USER_ID = "default"


def _to_response(data: dict) -> SuggestionResponse:
    return SuggestionResponse(**repository.to_response_dict(data))


@router.get("/suggestions", response_model=list[SuggestionResponse])
async def list_suggestions(
    db: aiosqlite.Connection = Depends(get_db),
) -> list[SuggestionResponse]:
    """Suggested sources awaiting review, best evidence first."""
    rows = await repository.list_by_status(db, DEFAULT_USER_ID, "suggested")
    return [_to_response(row) for row in rows]


@router.post("/run", response_model=DiscoveryRunStats)
async def run_discovery_now(
    use_llm: bool = Query(default=True),
    db: aiosqlite.Connection = Depends(get_db),
) -> DiscoveryRunStats:
    """Run a discovery pass immediately instead of waiting for the scheduler."""
    return await service.run_discovery(db, DEFAULT_USER_ID, use_llm=use_llm)


@router.post("/suggestions/{discovered_id}/accept", response_model=SuggestionResponse)
async def accept_suggestion(
    discovered_id: str,
    db: aiosqlite.Connection = Depends(get_db),
) -> SuggestionResponse:
    """Accept a suggestion: start monitoring the company as a source."""
    updated = await service.accept_suggestion(db, DEFAULT_USER_ID, discovered_id)
    if updated is None:
        raise HTTPException(
            status_code=404, detail="Suggestion not found or already decided"
        )
    return _to_response(updated)


@router.post("/suggestions/{discovered_id}/reject", response_model=SuggestionResponse)
async def reject_suggestion(
    discovered_id: str,
    db: aiosqlite.Connection = Depends(get_db),
) -> SuggestionResponse:
    """Dismiss a suggestion permanently; it will never be re-suggested."""
    updated = await service.reject_suggestion(db, DEFAULT_USER_ID, discovered_id)
    if updated is None:
        raise HTTPException(
            status_code=404, detail="Suggestion not found or already decided"
        )
    return _to_response(updated)
