"""Create a VideoPipelineRun and its full product/video/scene row tree in
one transaction. Pure DB construction — no Flow calls (orchestrator fills
status/media later)."""
from __future__ import annotations

from typing import Any

from flowboard.db.session import get_session
from flowboard.db.video_pipeline_models import (
    VideoPipelineRun, VideoPipelineProduct, VideoPipelineVideo, VideoPipelineScene,
)
from flowboard.services.video_pipeline.ids import new_short_id
from flowboard.services.video_pipeline.types import registry


class RunValidationError(Exception):
    pass


def _validate(type_key: str, inputs: dict[str, Any]) -> None:
    try:
        registry.get(type_key)
    except KeyError:
        raise RunValidationError(f"unknown type_key: {type_key}")
    products = inputs.get("products") or []
    if not products:
        raise RunValidationError("at least one product required")
    vc = int(inputs.get("video_count", 1))
    if not (1 <= vc <= 4):
        raise RunValidationError("video_count must be 1..4")
    sc = int(inputs.get("scene_count", 3))
    if not (1 <= sc <= 8):
        raise RunValidationError("scene_count must be 1..8")
    for key in ("character", "background"):
        if not (inputs.get(key) or {}).get("media_id"):
            raise RunValidationError(f"{key}.media_id required")


def create_run(*, type_key: str, inputs: dict[str, Any]) -> VideoPipelineRun:
    _validate(type_key, inputs)
    products = inputs["products"]
    video_count = int(inputs["video_count"])
    scene_count = int(inputs["scene_count"])

    with get_session() as s:
        run = VideoPipelineRun(short_id=new_short_id(), type_key=type_key, inputs=inputs)
        s.add(run)
        s.commit()
        s.refresh(run)
        rid = run.id

        for pi, prod in enumerate(products):
            s.add(VideoPipelineProduct(
                run_id=rid, product_index=pi,
                source=prod.get("source", "upload"),
                media_id=prod.get("media_id"),
                prompt=prod.get("prompt"),
            ))
            for vi in range(video_count):
                s.add(VideoPipelineVideo(run_id=rid, product_index=pi, video_index=vi))
                for sj in range(scene_count):
                    s.add(VideoPipelineScene(
                        run_id=rid, product_index=pi, video_index=vi, scene_index=sj))
        s.commit()
        s.refresh(run)
        return run
