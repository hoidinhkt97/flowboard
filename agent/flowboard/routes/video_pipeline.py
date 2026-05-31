"""Video Pipeline HTTP API. Phase 1 surface: /types + /templates CRUD.
Later phases extend this same router (inputs/resolve, runs, regen, ...)."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel
from sqlmodel import select

from flowboard.services.video_pipeline.types import registry
from flowboard.services.video_pipeline import templates as tpl
from flowboard.services.video_pipeline import run_builder, serializers
from flowboard.services.video_pipeline import input_resolver as ir
from flowboard.db.session import get_session
from flowboard.db.video_pipeline_models import VideoPipelineRun

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
def start_run(short_id: str):
    # Phase 2 stub: validate exists, flip pending->resolving. Phase 4 replaces
    # this body with asyncio.create_task(orchestrator.run(run_id)).
    with get_session() as s:
        run = s.exec(select(VideoPipelineRun).where(
            VideoPipelineRun.short_id == short_id)).first()
        if run is None:
            raise HTTPException(status_code=404, detail="run not found")
        if run.status == "pending":
            run.status = "resolving"
            s.add(run)
            s.commit()
    return Response(status_code=202)
