"""FastAPI routes for the lightweight Instaply web UI."""

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter(tags=["web"])

STATIC_DIR = Path(__file__).parent / "static"
INDEX_FILE = STATIC_DIR / "index.html"
ASSETS = ("styles.css", "app.js")


def _asset_version() -> str:
    """Version stamp from asset mtimes, so browsers refetch after a deploy."""
    return str(int(max((STATIC_DIR / name).stat().st_mtime for name in ASSETS)))


@router.get("/app", include_in_schema=False)
async def app_shell() -> HTMLResponse:
    """Serve the Instaply UI app shell with cache-busted asset URLs."""
    html = INDEX_FILE.read_text().replace("__ASSET_VERSION__", _asset_version())
    return HTMLResponse(html, headers={"Cache-Control": "no-cache"})
