"""Alert history API router."""

import aiosqlite
from fastapi import APIRouter, Depends, HTTPException, Query

from src.alerts import repository, service
from src.alerts.models import AlertResponse
from src.db.connection import get_db

router = APIRouter(prefix="/api/alerts", tags=["alerts"])

DEFAULT_USER_ID = "default"


def _to_response(alert: dict) -> AlertResponse:
    return AlertResponse(
        id=alert["id"],
        user_id=alert["user_id"],
        match_result_id=alert["match_result_id"],
        channel=alert["channel"],
        status=alert["status"],
        idempotency_key=alert["idempotency_key"],
        sent_at=str(alert["sent_at"]) if alert.get("sent_at") else None,
        failure_message=alert.get("failure_message"),
        created_at=str(alert["created_at"]) if alert.get("created_at") else None,
        match_summary=alert.get("match_summary"),
        score=alert.get("score"),
        job_title=alert.get("job_title"),
        company_name=alert.get("company_name"),
        job_url=alert.get("job_url"),
        matching_reasons=alert.get("matching_reasons") or [],
        missing_requirements=alert.get("missing_requirements") or [],
    )


@router.get("", response_model=list[AlertResponse])
async def list_alerts(
    status: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: aiosqlite.Connection = Depends(get_db),
) -> list[AlertResponse]:
    """List notification alerts."""
    alerts = await repository.list_alerts(
        db,
        DEFAULT_USER_ID,
        status=status,
        limit=limit,
        offset=offset,
    )
    return [_to_response(alert) for alert in alerts]


@router.post("/digest")
async def send_digest_now(
    lookback_days: int | None = Query(default=None, ge=1, le=365),
    db: aiosqlite.Connection = Depends(get_db),
) -> dict:
    """Send the match digest immediately instead of waiting for the schedule."""
    return await service.send_digest(
        db,
        DEFAULT_USER_ID,
        lookback_days=lookback_days,
    )


@router.get("/{alert_id}", response_model=AlertResponse)
async def get_alert(
    alert_id: str,
    db: aiosqlite.Connection = Depends(get_db),
) -> AlertResponse:
    """Get one alert."""
    alert = await repository.get_alert(db, alert_id, DEFAULT_USER_ID)
    if alert is None:
        raise HTTPException(status_code=404, detail="Alert not found")
    return _to_response(alert)

