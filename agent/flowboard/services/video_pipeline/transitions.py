"""Guarded status writes for run/video/scene + manifest refresh."""
from __future__ import annotations
from typing import Optional
from sqlmodel import select
from flowboard.db.session import get_session
from flowboard.db.models import _utcnow
from flowboard.db.video_pipeline_models import (
    VideoPipelineRun, VideoPipelineVideo, VideoPipelineScene,
)
from flowboard.services.video_pipeline import state_machine as sm
from flowboard.services.video_pipeline import storage, serializers


class InvalidTransition(Exception):
    pass


def _refresh_manifest(short_id: str) -> None:
    dto = serializers.serialize_run(short_id)
    if dto is not None:
        storage.write_manifest(short_id, dto)


def set_run_status(short_id: str, new_status: str, *, error: Optional[str] = None,
                   force: bool = False) -> None:
    with get_session() as s:
        run = s.exec(select(VideoPipelineRun).where(
            VideoPipelineRun.short_id == short_id)).first()
        if run is None:
            raise InvalidTransition(f"run {short_id} not found")
        if not force and run.status != new_status and not sm.can_transition_run(run.status, new_status):
            raise InvalidTransition(f"run {run.status} -> {new_status}")
        run.status = new_status
        if error is not None:
            run.error = error
        if new_status in ("done", "failed", "cancelled"):
            run.finished_at = _utcnow()
        if new_status == "resolving" and run.started_at is None:
            run.started_at = _utcnow()
        s.add(run)
        s.commit()
    _refresh_manifest(short_id)


def set_video_status(short_id: str, video_id: int, new_status: str, *,
                     error: Optional[str] = None, force: bool = False) -> None:
    with get_session() as s:
        v = s.get(VideoPipelineVideo, video_id)
        if v is None:
            raise InvalidTransition(f"video {video_id} not found")
        if not force and v.status != new_status and not sm.can_transition_video(v.status, new_status):
            raise InvalidTransition(f"video {v.status} -> {new_status}")
        v.status = new_status
        if error is not None:
            v.error = error
        v.updated_at = _utcnow()
        s.add(v)
        s.commit()
    _refresh_manifest(short_id)


def set_scene_status(short_id: str, scene_id: int, new_status: str, *,
                     error: Optional[str] = None, force: bool = False) -> None:
    with get_session() as s:
        sc = s.get(VideoPipelineScene, scene_id)
        if sc is None:
            raise InvalidTransition(f"scene {scene_id} not found")
        if not force and sc.status != new_status and not sm.can_transition_scene(sc.status, new_status):
            raise InvalidTransition(f"scene {sc.status} -> {new_status}")
        sc.status = new_status
        if error is not None:
            sc.error = error
        sc.updated_at = _utcnow()
        s.add(sc)
        s.commit()
    _refresh_manifest(short_id)
