"""Cascade-reset rules for regeneration. Each resets the minimal set and
invalidates the video's merged output. Refuses to reset rows that are
currently *_running (409 at the API layer)."""
from __future__ import annotations

from sqlmodel import select

from flowboard.db.session import get_session
from flowboard.db.models import _utcnow
from flowboard.db.video_pipeline_models import (
    VideoPipelineVideo, VideoPipelineScene,
)
from flowboard.services.video_pipeline import serializers, storage

_RUNNING = {"storyboard_running", "clip_running"}
_VIDEO_RUNNING = {"merging"}


class RegenConflict(Exception):
    pass


def _invalidate_merged(s, video_id: int) -> None:
    v = s.get(VideoPipelineVideo, video_id)
    if v.merged_local_path:
        try:
            from pathlib import Path
            p = Path(v.merged_local_path)
            if p.exists():
                p.unlink()
        except OSError:
            pass
    v.merged_local_path = None
    v.merged_url = None
    v.file_size_bytes = None
    v.duration_sec = None
    if v.status == "done":
        v.status = "scenes_done"
    s.add(v)


def _video_id_for_scene(s, scene_id: int) -> int:
    sc = s.get(VideoPipelineScene, scene_id)
    if sc is None:
        raise RegenConflict(f"scene {scene_id} not found")
    v = s.exec(select(VideoPipelineVideo).where(
        VideoPipelineVideo.run_id == sc.run_id,
        VideoPipelineVideo.product_index == sc.product_index,
        VideoPipelineVideo.video_index == sc.video_index)).first()
    return v.id


def _refresh(short_id: str) -> None:
    dto = serializers.serialize_run(short_id)
    if dto is not None:
        storage.write_manifest(short_id, dto)


def reset_for_clip(short_id: str, scene_id: int) -> None:
    with get_session() as s:
        sc = s.get(VideoPipelineScene, scene_id)
        if sc is None:
            raise RegenConflict("scene not found")
        if sc.status in _RUNNING:
            raise RegenConflict("scene is running")
        sc.clip_media_id = None
        sc.status = "storyboard_done" if sc.storyboard_media_id else "pending"
        sc.error = None
        sc.updated_at = _utcnow()
        s.add(sc)
        vid = _video_id_for_scene(s, scene_id)
        _invalidate_merged(s, vid)
        s.commit()
    _refresh(short_id)


def reset_for_storyboard(short_id: str, scene_id: int) -> None:
    with get_session() as s:
        sc = s.get(VideoPipelineScene, scene_id)
        if sc is None:
            raise RegenConflict("scene not found")
        if sc.status in _RUNNING:
            raise RegenConflict("scene is running")
        sc.storyboard_media_id = None
        sc.clip_media_id = None
        sc.status = "pending"
        sc.error = None
        sc.updated_at = _utcnow()
        s.add(sc)
        vid = _video_id_for_scene(s, scene_id)
        _invalidate_merged(s, vid)
        s.commit()
    _refresh(short_id)


def reset_for_composite(short_id: str, video_id: int) -> None:
    with get_session() as s:
        v = s.get(VideoPipelineVideo, video_id)
        if v is None:
            raise RegenConflict("video not found")
        if v.status in _VIDEO_RUNNING:
            raise RegenConflict("video is merging")
        scenes = s.exec(select(VideoPipelineScene).where(
            VideoPipelineScene.run_id == v.run_id,
            VideoPipelineScene.product_index == v.product_index,
            VideoPipelineScene.video_index == v.video_index)).all()
        if any(sc.status in _RUNNING for sc in scenes):
            raise RegenConflict("a scene is running")
        for sc in scenes:
            sc.storyboard_media_id = None
            sc.clip_media_id = None
            sc.status = "pending"
            sc.error = None
            sc.updated_at = _utcnow()
            s.add(sc)
        v.composite_media_id = None
        v.composite_attempts = (v.composite_attempts or 0) + 1
        _invalidate_merged(s, video_id)
        v.status = "pending"
        s.add(v)
        s.commit()
    _refresh(short_id)


def reset_for_video(short_id: str, video_id: int) -> None:
    reset_for_composite(short_id, video_id)


def reset_for_remerge(short_id: str, video_id: int) -> None:
    with get_session() as s:
        v = s.get(VideoPipelineVideo, video_id)
        if v is None:
            raise RegenConflict("video not found")
        if v.status in _VIDEO_RUNNING:
            raise RegenConflict("video is merging")
        _invalidate_merged(s, video_id)
        v.status = "scenes_done"
        s.add(v)
        s.commit()
    _refresh(short_id)
