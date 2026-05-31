from __future__ import annotations

from typing import Optional

from sqlmodel import select

from flowboard.db.session import get_session
from flowboard.db.models import _utcnow
from flowboard.db.video_pipeline_models import VideoPipelineTemplate


class TemplateNotFoundError(Exception):
    pass


class TemplateProtectedError(Exception):
    pass


_BUILTINS = [
    {"name": "Review nhanh 9:16", "type_key": "product_review",
     "params": {"aspect_ratio": "9:16", "scene_count": 3, "quality": "fast",
                "crossfade_sec": 0.0, "audio_enabled": True, "video_count": 1,
                "concurrency_cap": 4, "script_brief": ""}},
    {"name": "Review chuẩn 9:16", "type_key": "product_review",
     "params": {"aspect_ratio": "9:16", "scene_count": 4, "quality": "standard",
                "crossfade_sec": 0.4, "audio_enabled": True, "video_count": 2,
                "concurrency_cap": 4, "script_brief": ""}},
]


def create_template(*, name: str, type_key: str, params: dict,
                    is_builtin: bool = False, position: int = 0) -> VideoPipelineTemplate:
    with get_session() as s:
        row = VideoPipelineTemplate(name=name, type_key=type_key, params=params,
                                    is_builtin=is_builtin, position=position)
        s.add(row)
        s.commit()
        s.refresh(row)
        return row


def list_templates() -> list[VideoPipelineTemplate]:
    with get_session() as s:
        rows = s.exec(
            select(VideoPipelineTemplate).order_by(
                VideoPipelineTemplate.position, VideoPipelineTemplate.id)
        ).all()
        return list(rows)


def _get(s, template_id: int) -> VideoPipelineTemplate:
    row = s.get(VideoPipelineTemplate, template_id)
    if row is None:
        raise TemplateNotFoundError(str(template_id))
    return row


def update_template(template_id: int, *, name: Optional[str] = None,
                    params: Optional[dict] = None,
                    position: Optional[int] = None) -> VideoPipelineTemplate:
    with get_session() as s:
        row = _get(s, template_id)
        if row.is_builtin:
            raise TemplateProtectedError(str(template_id))
        if name is not None:
            row.name = name
        if params is not None:
            row.params = params
        if position is not None:
            row.position = position
        row.updated_at = _utcnow()
        s.add(row)
        s.commit()
        s.refresh(row)
        return row


def delete_template(template_id: int) -> None:
    with get_session() as s:
        row = _get(s, template_id)
        if row.is_builtin:
            raise TemplateProtectedError(str(template_id))
        s.delete(row)
        s.commit()


def seed_builtins() -> None:
    """Idempotent: insert builtin templates only if not already present."""
    with get_session() as s:
        existing = {
            r.name for r in s.exec(
                select(VideoPipelineTemplate).where(
                    VideoPipelineTemplate.is_builtin == True)  # noqa: E712
            ).all()
        }
    for i, spec in enumerate(_BUILTINS):
        if spec["name"] not in existing:
            create_template(name=spec["name"], type_key=spec["type_key"],
                            params=spec["params"], is_builtin=True, position=i)
