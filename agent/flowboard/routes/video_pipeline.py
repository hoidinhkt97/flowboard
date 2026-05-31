"""Video Pipeline HTTP API. Phase 1 surface: /types + /templates CRUD.
Later phases extend this same router (inputs/resolve, runs, regen, ...)."""
from __future__ import annotations

import asyncio
import io
import logging
import zipfile
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Response
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel
from sqlmodel import select

from flowboard.services.video_pipeline.types import registry
from flowboard.services.video_pipeline import templates as tpl
from flowboard.services.video_pipeline import run_builder, serializers
from flowboard.services.video_pipeline import input_resolver as ir
from flowboard.services.video_pipeline import orchestrator as _vp_orchestrator
from flowboard.db.session import get_session
from flowboard.db.video_pipeline_models import VideoPipelineRun, VideoPipelineVideo

logger = logging.getLogger(__name__)
_active_vp_tasks: dict[str, asyncio.Task] = {}

# indirection so tests can monkeypatch the coroutine fn
_orchestrator_run = _vp_orchestrator.run

router = APIRouter(prefix="/api/video-pipeline", tags=["video-pipeline"])


@router.get("/types")
def list_types():
    return registry.list_types()


class TemplateCreate(BaseModel):
    name: str
    type_key: str = "product_review"
    params: dict = {}


class TemplatePatch(BaseModel):
    name: Optional[str] = None
    params: Optional[dict] = None
    position: Optional[int] = None


def _serialize(t) -> dict:
    return {
        "id": t.id, "name": t.name, "type_key": t.type_key, "params": t.params,
        "is_builtin": t.is_builtin, "position": t.position,
        "created_at": t.created_at, "updated_at": t.updated_at,
    }


@router.get("/templates")
def list_templates():
    return [_serialize(t) for t in tpl.list_templates()]


@router.post("/templates", status_code=201)
def create_template(body: TemplateCreate):
    row = tpl.create_template(name=body.name, type_key=body.type_key, params=body.params)
    return _serialize(row)


@router.patch("/templates/{template_id}")
def patch_template(template_id: int, body: TemplatePatch):
    try:
        row = tpl.update_template(template_id, name=body.name, params=body.params,
                                  position=body.position)
    except tpl.TemplateNotFoundError:
        raise HTTPException(status_code=404, detail="template not found")
    except tpl.TemplateProtectedError:
        raise HTTPException(status_code=403, detail="builtin template is read-only")
    return _serialize(row)


@router.delete("/templates/{template_id}", status_code=204)
def delete_template(template_id: int):
    try:
        tpl.delete_template(template_id)
    except tpl.TemplateNotFoundError:
        raise HTTPException(status_code=404, detail="template not found")
    except tpl.TemplateProtectedError:
        raise HTTPException(status_code=403, detail="builtin template is read-only")
    return None


class ResolveBody(BaseModel):
    kind: str
    source: str
    media_id: Optional[str] = None
    description: Optional[str] = None
    project_id: Optional[str] = None
    aspect_ratio: str = "9:16"
    variant_count: int = 4


@router.post("/inputs/resolve")
async def resolve_input(body: ResolveBody):
    if body.source in ("upload", "gen"):
        if not body.media_id:
            raise HTTPException(status_code=422, detail="media_id required for this source")
        return {"media_id": body.media_id}
    if body.source == "ai_gen":
        if not (body.description and body.project_id):
            raise HTTPException(status_code=422, detail="description + project_id required")
        try:
            out = await ir.resolve_ai_gen(
                description=body.description, project_id=body.project_id,
                aspect_ratio=body.aspect_ratio, variant_count=body.variant_count)
        except ir.InputResolveError as e:
            raise HTTPException(status_code=502, detail=str(e))
        return out
    raise HTTPException(status_code=422, detail=f"unknown source: {body.source}")


class RunCreate(BaseModel):
    type_key: str = "product_review"
    inputs: dict


@router.post("/runs", status_code=201)
def create_run(body: RunCreate):
    try:
        run = run_builder.create_run(type_key=body.type_key, inputs=body.inputs)
    except run_builder.RunValidationError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return serializers.serialize_run(run.short_id)


@router.get("/runs/{short_id}")
def get_run(short_id: str):
    dto = serializers.serialize_run(short_id)
    if dto is None:
        raise HTTPException(status_code=404, detail="run not found")
    return dto


@router.post("/runs/{short_id}/start", status_code=202)
async def start_run(short_id: str):
    with get_session() as s:
        run = s.exec(select(VideoPipelineRun).where(
            VideoPipelineRun.short_id == short_id)).first()
        if run is None:
            raise HTTPException(status_code=404, detail="run not found")

    task = asyncio.create_task(_orchestrator_run(short_id), name=f"vp-run-{short_id}")
    _active_vp_tasks[short_id] = task

    def _cleanup(t: asyncio.Task) -> None:
        _active_vp_tasks.pop(short_id, None)
        exc = t.exception() if not t.cancelled() else None
        if exc is not None:
            logger.exception("video-pipeline run %s crashed", short_id, exc_info=exc)
            try:
                from flowboard.services.video_pipeline import transitions as tr
                tr.set_run_status(short_id, "failed", error=str(exc), force=True)
            except Exception:  # noqa: BLE001
                pass

    task.add_done_callback(_cleanup)
    return Response(status_code=202)


def _load_video(short_id: str, video_id: int):
    with get_session() as s:
        run = s.exec(select(VideoPipelineRun).where(
            VideoPipelineRun.short_id == short_id)).first()
        if run is None:
            raise HTTPException(status_code=404, detail="run not found")
        v = s.get(VideoPipelineVideo, video_id)
        if v is None or v.run_id != run.id:
            raise HTTPException(status_code=404, detail="video not found")
        return run, v


@router.get("/runs/{short_id}/videos/{video_id}/preview")
def preview_video(short_id: str, video_id: int):
    _run, v = _load_video(short_id, video_id)
    if not v.merged_local_path or not Path(v.merged_local_path).exists():
        raise HTTPException(status_code=404, detail="merged video not ready")
    return FileResponse(v.merged_local_path, media_type="video/mp4")


@router.get("/runs/{short_id}/videos/{video_id}/download")
def download_video(short_id: str, video_id: int):
    _run, v = _load_video(short_id, video_id)
    if not v.merged_local_path or not Path(v.merged_local_path).exists():
        raise HTTPException(status_code=404, detail="merged video not ready")
    fname = f"{short_id}-p{v.product_index}-v{v.video_index}.mp4"
    return FileResponse(v.merged_local_path, media_type="video/mp4", filename=fname)


@router.get("/runs/{short_id}/download-all.zip")
def download_all(short_id: str):
    with get_session() as s:
        run = s.exec(select(VideoPipelineRun).where(
            VideoPipelineRun.short_id == short_id)).first()
        if run is None:
            raise HTTPException(status_code=404, detail="run not found")
        videos = s.exec(select(VideoPipelineVideo).where(
            VideoPipelineVideo.run_id == run.id)).all()

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as zf:
        for v in videos:
            if v.merged_local_path and Path(v.merged_local_path).exists():
                zf.write(v.merged_local_path,
                         arcname=f"p{v.product_index}-v{v.video_index}.mp4")
    buf.seek(0)
    headers = {"Content-Disposition": f'attachment; filename="{short_id}.zip"'}
    return StreamingResponse(buf, media_type="application/zip", headers=headers)
