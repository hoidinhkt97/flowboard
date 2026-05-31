"""Video Pipeline HTTP API. Phase 1 surface: /types + /templates CRUD.
Later phases extend this same router (inputs/resolve, runs, regen, ...)."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from flowboard.services.video_pipeline.types import registry
from flowboard.services.video_pipeline import templates as tpl

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
