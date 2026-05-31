"""Filesystem layout + manifest roundtrip for video-pipeline runs.

storage/video_pipeline/<short_id>/{composites,storyboards,clips,merged}/...
plus manifest.json (resume snapshot). Input ref media stays in the media
cache (services/media), not copied here.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Optional

from flowboard.config import STORAGE_DIR

_BASE = "video_pipeline"
_SUBDIRS = ("composites", "storyboards", "clips", "merged")


def run_dir(short_id: str) -> Path:
    return STORAGE_DIR / _BASE / short_id


def ensure_run_dirs(short_id: str) -> Path:
    base = run_dir(short_id)
    for sub in _SUBDIRS:
        (base / sub).mkdir(parents=True, exist_ok=True)
    return base


def composite_path(short_id: str, product_index: int, video_index: int) -> Path:
    return run_dir(short_id) / "composites" / f"p{product_index}-v{video_index}.png"


def storyboard_path(short_id: str, product_index: int, video_index: int, scene_index: int) -> Path:
    return run_dir(short_id) / "storyboards" / f"p{product_index}-v{video_index}-s{scene_index}.png"


def clip_path(short_id: str, product_index: int, video_index: int, scene_index: int) -> Path:
    return run_dir(short_id) / "clips" / f"p{product_index}-v{video_index}-s{scene_index}.mp4"


def merged_path(short_id: str, product_index: int, video_index: int) -> Path:
    return run_dir(short_id) / "merged" / f"p{product_index}-v{video_index}.mp4"


def manifest_path(short_id: str) -> Path:
    return run_dir(short_id) / "manifest.json"


def write_manifest(short_id: str, payload: dict[str, Any]) -> None:
    ensure_run_dirs(short_id)
    target = manifest_path(short_id)
    fd, tmp = tempfile.mkstemp(dir=str(target.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2, default=str)
        os.replace(tmp, target)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def read_manifest(short_id: str) -> Optional[dict[str, Any]]:
    p = manifest_path(short_id)
    if not p.exists():
        return None
    with p.open(encoding="utf-8") as f:
        return json.load(f)
