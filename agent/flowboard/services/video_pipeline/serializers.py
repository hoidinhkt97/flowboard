"""Load a run + children into the nested dict used by the polling API and
manifest.json. Single source of truth so both stay identical."""
from __future__ import annotations

from typing import Any, Optional

from sqlmodel import select

from flowboard.db.session import get_session
from flowboard.db.video_pipeline_models import (
    VideoPipelineRun, VideoPipelineProduct, VideoPipelineVideo, VideoPipelineScene,
)


def _scene_dto(sc: VideoPipelineScene) -> dict[str, Any]:
    return {
        "id": sc.id, "scene_index": sc.scene_index,
        "image_prompt": sc.image_prompt, "video_prompt": sc.video_prompt,
        "storyboard_media_id": sc.storyboard_media_id,
        "clip_media_id": sc.clip_media_id,
        "status": sc.status, "error": sc.error,
    }


def _video_dto(v: VideoPipelineVideo, scenes: list[VideoPipelineScene]) -> dict[str, Any]:
    return {
        "id": v.id, "video_index": v.video_index,
        "composite_media_id": v.composite_media_id,
        "merged_url": v.merged_url, "status": v.status, "error": v.error,
        "duration_sec": v.duration_sec, "file_size_bytes": v.file_size_bytes,
        "scenes": [_scene_dto(s) for s in sorted(scenes, key=lambda x: x.scene_index)],
    }


def serialize_run(short_id: str) -> Optional[dict[str, Any]]:
    with get_session() as s:
        run = s.exec(select(VideoPipelineRun).where(
            VideoPipelineRun.short_id == short_id)).first()
        if run is None:
            return None
        rid = run.id
        products = s.exec(select(VideoPipelineProduct).where(
            VideoPipelineProduct.run_id == rid)).all()
        videos = s.exec(select(VideoPipelineVideo).where(
            VideoPipelineVideo.run_id == rid)).all()
        scenes = s.exec(select(VideoPipelineScene).where(
            VideoPipelineScene.run_id == rid)).all()

    scenes_by_video: dict[tuple[int, int], list] = {}
    for sc in scenes:
        scenes_by_video.setdefault((sc.product_index, sc.video_index), []).append(sc)
    videos_by_product: dict[int, list] = {}
    for v in videos:
        videos_by_product.setdefault(v.product_index, []).append(v)

    product_dtos = []
    for p in sorted(products, key=lambda x: x.product_index):
        vids = sorted(videos_by_product.get(p.product_index, []), key=lambda x: x.video_index)
        product_dtos.append({
            "id": p.id, "product_index": p.product_index,
            "media_id": p.media_id, "source": p.source,
            "videos": [_video_dto(v, scenes_by_video.get((p.product_index, v.video_index), []))
                       for v in vids],
        })

    clips_total = len(scenes)
    clips_done = sum(1 for sc in scenes if sc.status in ("clip_done", "merged"))
    return {
        "short_id": run.short_id, "type_key": run.type_key,
        "flow_project_id": run.flow_project_id, "inputs": run.inputs,
        "status": run.status, "error": run.error, "cancelled": run.cancelled,
        "created_at": run.created_at, "started_at": run.started_at,
        "finished_at": run.finished_at,
        "products": product_dtos,
        "progress": {"clips_total": clips_total, "clips_done": clips_done},
    }
