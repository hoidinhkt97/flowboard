"""Media cache routes.

`GET /media/:media_id` streams bytes (cache hit → immediate; miss → one-shot
fetch from GCS then cache). `GET /api/media/:media_id/status` exposes cache
state for the frontend to poll while it waits for a URL to arrive.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from sqlmodel import select

from flowboard.db import get_session
from flowboard.db.models import Account, Asset
from flowboard.deps import get_current_account
from flowboard.services import media as media_service
from flowboard.services import object_storage
from flowboard.services.media import is_valid_media_id

logger = logging.getLogger(__name__)

bytes_router = APIRouter(tags=["media"])
api_router = APIRouter(prefix="/api/media", tags=["media"])


@bytes_router.get("/media/{media_id:path}")
async def get_media_bytes(media_id: str):
    media_id = media_service.normalize_media_id(media_id)
    if not media_service.is_valid_media_id(media_id):
        raise HTTPException(status_code=400, detail="invalid media_id")

    cached = media_service.cached_path(media_id)
    if cached is not None:
        return FileResponse(
            path=str(cached),
            media_type=media_service._mime_from_ext(cached.suffix),
        )

    # Cache miss — try one fetch through the stored URL.
    result = await media_service.fetch_and_cache(media_id)
    if result is None:
        status = media_service.status(media_id)
        return JSONResponse(status_code=404, content=status)
    _bytes, mime, path = result
    return FileResponse(path=str(path), media_type=mime)


@api_router.get("/{media_id}/status")
def get_media_status(media_id: str):
    media_id = media_service.normalize_media_id(media_id)
    if not media_service.is_valid_media_id(media_id):
        return JSONResponse(
            status_code=400,
            content={"available": False, "has_url": False, "reason": "invalid_id"},
        )
    return media_service.status(media_id)


@api_router.get("/{media_id}/url")
async def get_media_url(
    media_id: str,
    acct: Account = Depends(get_current_account),
):
    """Return a URL to access this media asset.

    Returns a presigned S3 GET URL when S3 is configured, otherwise
    the local /media/:id serve path. Always verifies account ownership."""
    if not is_valid_media_id(media_id):
        raise HTTPException(status_code=404, detail="not found")

    with get_session() as s:
        asset = s.exec(
            select(Asset).where(
                Asset.uuid_media_id == media_id,
                Asset.account_id == acct.id,
            )
        ).first()

    if asset is None:
        raise HTTPException(status_code=404, detail="not found")

    if asset.s3_key and object_storage.is_configured():
        url = await object_storage.presigned_get_url(asset.s3_key, expires=300)
        return {"url": url, "expires_in": 300}

    return {"url": f"/media/{media_id}", "expires_in": None}


@api_router.get("/_debug/assets")
def debug_assets():
    """Dev-only dump of every Asset row so we can see what URLs the extension
    has actually pushed to the agent. Remove once media flow is stable.
    """
    from sqlmodel import select as _select

    from flowboard.db import get_session
    from flowboard.db.models import Asset

    with get_session() as s:
        rows = s.exec(_select(Asset)).all()
        return {
            "count": len(rows),
            "rows": [
                {
                    "id": r.id,
                    "media_id": r.uuid_media_id,
                    "has_url": bool(r.url),
                    "url_head": (r.url or "")[:80] if r.url else None,
                    "mime": r.mime,
                    "cached": bool(r.local_path),
                    "node_id": r.node_id,
                }
                for r in rows
            ],
        }
