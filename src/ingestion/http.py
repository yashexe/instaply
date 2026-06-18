"""
Shared HTTP fetch helper for ATS adapters.

Wraps httpx with bounded retries and exponential backoff so transient
upstream failures (network errors, 429s, 5xx) do not immediately count
as a source failure, while persistent failures surface as
AdapterFetchError and feed source health tracking.
"""

import asyncio
from typing import Any

import httpx
import structlog

logger = structlog.get_logger()

DEFAULT_TIMEOUT = 30.0
DEFAULT_HEADERS = {"User-Agent": "Instaply/0.1"}
MAX_ATTEMPTS = 3
BACKOFF_BASE_SECONDS = 1.0

# Status codes worth retrying — rate limits and server-side errors.
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


class AdapterFetchError(Exception):
    """Raised when an adapter cannot fetch jobs after retries."""


def _is_retryable(exc: Exception) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in RETRYABLE_STATUS_CODES
    return isinstance(exc, httpx.RequestError)


async def fetch_json(
    method: str,
    url: str,
    *,
    json_body: dict | None = None,
    provider: str = "unknown",
    max_attempts: int = MAX_ATTEMPTS,
    quiet_4xx: bool = False,
) -> Any:
    """Fetch and decode a JSON response with retries.

    Retries network errors, 429, and 5xx responses with exponential
    backoff. Other HTTP errors (e.g. 404) fail immediately. Raises
    AdapterFetchError once attempts are exhausted or on a non-retryable
    failure.
    """
    last_error: Exception | None = None

    for attempt in range(1, max_attempts + 1):
        try:
            async with httpx.AsyncClient(
                timeout=DEFAULT_TIMEOUT,
                headers=DEFAULT_HEADERS,
                follow_redirects=True,
            ) as client:
                resp = await client.request(method, url, json=json_body)
                resp.raise_for_status()
                return resp.json()
        except (httpx.HTTPStatusError, httpx.RequestError) as exc:
            last_error = exc
            status = (
                exc.response.status_code
                if isinstance(exc, httpx.HTTPStatusError)
                else None
            )
            if not _is_retryable(exc) or attempt == max_attempts:
                break
            delay = BACKOFF_BASE_SECONDS * (2 ** (attempt - 1))
            logger.warning(
                "adapter.fetch_retry",
                provider=provider,
                url=url,
                attempt=attempt,
                status=status,
                error=str(exc),
                retry_in_seconds=delay,
            )
            await asyncio.sleep(delay)
        except ValueError as exc:
            # JSON decode failure — not retryable, the payload is broken.
            last_error = exc
            break

    if isinstance(last_error, httpx.HTTPStatusError):
        message = f"HTTP {last_error.response.status_code} from {url}"
        # Callers that probe speculatively (discovery) expect 4xx misses;
        # don't report those as errors.
        if quiet_4xx and 400 <= last_error.response.status_code < 500:
            logger.debug(
                "adapter.fetch_miss", provider=provider, url=url, error=message
            )
            raise AdapterFetchError(message) from last_error
    else:
        message = f"{type(last_error).__name__}: {last_error}"
    logger.error("adapter.fetch_failed", provider=provider, url=url, error=message)
    raise AdapterFetchError(message) from last_error
