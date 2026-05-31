"""Ensure a clip media_id exists as a local file at a destination path."""
from __future__ import annotations

import shutil
from pathlib import Path

from flowboard.services import media as media_service


async def fetch_clip_to(media_id: str, dest: Path) -> Path:
    src = media_service.cached_path(media_id)
    if src is None:
        raise FileNotFoundError(f"clip {media_id} not available locally")
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dest)
    return dest
