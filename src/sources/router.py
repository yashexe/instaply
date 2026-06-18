"""Sources API router."""

import aiosqlite
from fastapi import APIRouter, Depends, HTTPException, Query

from src.db.connection import get_db
from src.ingestion.service import poll_source_by_id
from src.sources import repository
from src.sources.detector import detect_provider, test_source
from src.sources.models import SourceInput, SourceResponse, SourceTestResult, SourceUpdate

router = APIRouter(prefix="/api/sources", tags=["sources"])

DEFAULT_USER_ID = "default"


def _to_response(data: dict) -> SourceResponse:
    return SourceResponse(
        id=data["id"],
        user_id=data["user_id"],
        company_name=data["company_name"],
        provider=data["provider"],
        source_url=data["source_url"],
        normalized_url=data.get("normalized_url"),
        priority=data.get("priority") or "normal",
        status=data.get("status") or "active",
        fetch_interval_seconds=data.get("fetch_interval_seconds"),
        last_success_at=str(data["last_success_at"]) if data.get("last_success_at") else None,
        last_error_at=str(data["last_error_at"]) if data.get("last_error_at") else None,
        last_error_message=data.get("last_error_message"),
        consecutive_error_count=data.get("consecutive_error_count") or 0,
        created_at=str(data["created_at"]) if data.get("created_at") else None,
        updated_at=str(data["updated_at"]) if data.get("updated_at") else None,
    )


@router.post("/test", response_model=SourceTestResult)
async def test_source_url(body: SourceInput) -> SourceTestResult:
    """Detect and test a source URL without saving it."""
    provider, normalized_url, _company = detect_provider(body.url)
    return await test_source(normalized_url, provider)


@router.post("", response_model=SourceResponse)
async def create_source(
    body: SourceInput,
    db: aiosqlite.Connection = Depends(get_db),
) -> SourceResponse:
    """Create a monitored job source."""
    provider, normalized_url, detected_company = detect_provider(body.url)
    company_name = body.company_name or detected_company or "Unknown"

    source_id = await repository.create_source(
        db,
        DEFAULT_USER_ID,
        company_name=company_name,
        provider=provider,
        source_url=body.url,
        normalized_url=normalized_url,
        priority=body.priority,
    )
    source = await repository.get_source(db, source_id, DEFAULT_USER_ID)
    if source is None:
        raise HTTPException(status_code=500, detail="Failed to create source")
    return _to_response(source)


@router.get("", response_model=list[SourceResponse])
async def list_sources(
    status: str | None = Query(default=None),
    db: aiosqlite.Connection = Depends(get_db),
) -> list[SourceResponse]:
    """List monitored sources."""
    sources = await repository.list_sources(db, DEFAULT_USER_ID, status=status)
    return [_to_response(source) for source in sources]


@router.get("/{source_id}", response_model=SourceResponse)
async def get_source(
    source_id: str,
    db: aiosqlite.Connection = Depends(get_db),
) -> SourceResponse:
    """Get one monitored source."""
    source = await repository.get_source(db, source_id, DEFAULT_USER_ID)
    if source is None:
        raise HTTPException(status_code=404, detail="Source not found")
    return _to_response(source)


@router.patch("/{source_id}", response_model=SourceResponse)
async def update_source(
    source_id: str,
    body: SourceUpdate,
    db: aiosqlite.Connection = Depends(get_db),
) -> SourceResponse:
    """Update source status, priority, or company name."""
    source = await repository.update_source(
        db,
        source_id,
        DEFAULT_USER_ID,
        body.model_dump(exclude_unset=True),
    )
    if source is None:
        raise HTTPException(status_code=404, detail="Source not found")
    return _to_response(source)


@router.delete("/{source_id}")
async def delete_source(
    source_id: str,
    db: aiosqlite.Connection = Depends(get_db),
) -> dict:
    """Delete a monitored source."""
    deleted = await repository.delete_source(db, source_id, DEFAULT_USER_ID)
    if not deleted:
        raise HTTPException(status_code=404, detail="Source not found")
    return {"deleted": True}


@router.post("/{source_id}/poll")
async def poll_source_now(
    source_id: str,
    score_matches: bool = Query(default=True),
    db: aiosqlite.Connection = Depends(get_db),
) -> dict:
    """Immediately poll a source instead of waiting for the scheduler."""
    source = await repository.get_source(db, source_id, DEFAULT_USER_ID)
    if source is None:
        raise HTTPException(status_code=404, detail="Source not found")
    result = await poll_source_by_id(db, source_id, score_matches=score_matches)
    if result is None:
        raise HTTPException(status_code=404, detail="Source not found")
    return result
