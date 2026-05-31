"""Video-pipeline orchestrator: idempotent, resume-safe, concurrency-capped.

run(short_id) walks product -> video -> scene, advancing DB status through the
guarded transitions and producing composites/storyboards/clips. All external
I/O is funneled through a `deps` object (DefaultDeps in production) so tests
inject deterministic fakes. Merge step is added in Phase 5.
"""
from __future__ import annotations

import asyncio
from typing import Any, Optional

from sqlmodel import select

from flowboard.db.session import get_session
from flowboard.db.video_pipeline_models import (
    VideoPipelineRun, VideoPipelineProduct, VideoPipelineVideo, VideoPipelineScene,
)
from flowboard.services.video_pipeline import transitions as tr
from flowboard.services.video_pipeline import storage
from flowboard.services.video_pipeline.clip_gen import ClipGenError
from flowboard.services.video_pipeline.storyboard_gen import StoryboardGenError


class DefaultDeps:
    """Production generation deps — delegate to the real services."""

    async def ensure_project(self, run: VideoPipelineRun) -> str:
        from flowboard.services.flow_sdk import get_flow_sdk
        if run.flow_project_id:
            return run.flow_project_id
        resp = await get_flow_sdk().create_project(f"VideoPipeline {run.short_id}")
        pid = resp.get("project_id")
        if not pid:
            raise RuntimeError(resp.get("error") or "create_project failed")
        with get_session() as s:
            r = s.get(VideoPipelineRun, run.id)
            r.flow_project_id = pid
            s.add(r)
            s.commit()
        return pid

    async def gen_composites(self, **k):
        from flowboard.services.video_pipeline.composite_gen import generate_composites
        return await generate_composites(**k)

    async def plan_script(self, *, script_brief, scene_count):
        from flowboard.services.video_pipeline.script_planner import plan_script
        return await plan_script(script_brief=script_brief, scene_count=scene_count)

    async def gen_storyboard(self, **k):
        from flowboard.services.video_pipeline.storyboard_gen import generate_storyboard
        k.pop("product_index", None); k.pop("video_index", None); k.pop("scene_index", None)
        return await generate_storyboard(**k)

    async def gen_clip(self, *, product_index, video_index, scene_index, **k):
        from flowboard.services.video_pipeline.clip_gen import generate_clip
        return await generate_clip(**k)

    async def fetch_clip_to(self, media_id, dest):
        from flowboard.services.video_pipeline.clip_fetch import fetch_clip_to
        return await fetch_clip_to(media_id, dest)

    async def merge(self, *, clips, out_path, crossfade_sec, audio, durations=None):
        from flowboard.services.video_pipeline.merger import merge_clips
        return await merge_clips(clips=clips, out_path=out_path,
                                 crossfade_sec=crossfade_sec, audio=audio,
                                 durations=durations)


def _is_cancelled(short_id: str) -> bool:
    with get_session() as s:
        run = s.exec(select(VideoPipelineRun).where(
            VideoPipelineRun.short_id == short_id)).first()
        return bool(run and run.cancelled)


def _reload_run(run_id: int) -> VideoPipelineRun:
    with get_session() as s:
        return s.get(VideoPipelineRun, run_id)


async def run(short_id: str, *, deps: Optional[Any] = None) -> None:
    deps = deps or DefaultDeps()
    storage.ensure_run_dirs(short_id)

    with get_session() as s:
        run_row = s.exec(select(VideoPipelineRun).where(
            VideoPipelineRun.short_id == short_id)).first()
        if run_row is None:
            return
        inputs = dict(run_row.inputs)
        run_obj_id = run_row.id
        already_cancelled = run_row.cancelled

    if already_cancelled:
        tr.set_run_status(short_id, "cancelled", force=True)
        return

    tr.set_run_status(short_id, "resolving", force=True)
    project_id = await deps.ensure_project(_reload_run(run_obj_id))
    tr.set_run_status(short_id, "generating", force=True)

    aspect = inputs.get("aspect_ratio", "9:16")
    quality = inputs.get("quality", "standard")
    cap = int(inputs.get("concurrency_cap", 4))
    crossfade_sec = float(inputs.get("crossfade_sec", 0.0))
    audio = bool(inputs.get("audio_enabled", True))
    sem = asyncio.Semaphore(cap)
    character_mid = inputs["character"]["media_id"]
    background_mid = inputs["background"]["media_id"]
    script_brief = inputs.get("script_brief", "")

    with get_session() as s:
        products = sorted(
            s.exec(select(VideoPipelineProduct).where(
                VideoPipelineProduct.run_id == run_obj_id)).all(),
            key=lambda p: p.product_index)
        products = [(p.product_index, p.media_id) for p in products]

    for product_index, product_mid in products:
        if _is_cancelled(short_id):
            tr.set_run_status(short_id, "cancelled", force=True)
            return
        await _run_product(short_id, run_obj_id, deps, project_id, product_index,
                           product_mid, character_mid, background_mid, script_brief,
                           aspect, quality, sem, crossfade_sec, audio)

    if _is_cancelled(short_id):
        tr.set_run_status(short_id, "cancelled", force=True)
        return

    # Finalize: if all videos are terminal, mark run done
    with get_session() as s:
        videos = s.exec(select(VideoPipelineVideo).where(
            VideoPipelineVideo.run_id == run_obj_id)).all()
    if videos and all(v.status in ("done", "failed") for v in videos):
        tr.set_run_status(short_id, "done", force=True)


async def _run_product(short_id, run_id, deps, project_id, product_index, product_mid,
                       character_mid, background_mid, script_brief, aspect, quality, sem,
                       crossfade_sec, audio):
    with get_session() as s:
        videos = sorted(
            s.exec(select(VideoPipelineVideo).where(
                VideoPipelineVideo.run_id == run_id,
                VideoPipelineVideo.product_index == product_index)).all(),
            key=lambda v: v.video_index)
        video_rows = [(v.id, v.video_index, v.composite_media_id, v.status) for v in videos]

    n = len(video_rows)
    need_composite = [v for v in video_rows if not v[2]]
    if need_composite:
        composites = await deps.gen_composites(
            character_media_id=character_mid, product_media_id=product_mid,
            project_id=project_id, aspect_ratio=aspect, variant_count=n,
            script_brief=script_brief)
        with get_session() as s:
            for (vid_id, vidx, comp_mid, _status), entry in zip(video_rows, composites):
                v = s.get(VideoPipelineVideo, vid_id)
                if not v.composite_media_id:
                    v.composite_media_id = entry["media_id"]
                    s.add(v)
            s.commit()
        for vid_id, vidx, _comp, _status in video_rows:
            tr.set_video_status(short_id, vid_id, "composite_done")

    async def run_one_video(vid_id, vidx):
        async with sem:
            if _is_cancelled(short_id):
                return
            await _run_video(short_id, run_id, deps, project_id, product_index, vidx,
                             vid_id, background_mid, script_brief, aspect, quality,
                             crossfade_sec, audio)

    await asyncio.gather(*[run_one_video(vid_id, vidx)
                           for vid_id, vidx, _c, _s in video_rows])


async def _run_video(short_id, run_id, deps, project_id, product_index, video_index,
                     video_id, background_mid, script_brief, aspect, quality,
                     crossfade_sec, audio):
    with get_session() as s:
        v = s.get(VideoPipelineVideo, video_id)
        composite_mid = v.composite_media_id
        video_status = v.status
        scenes = sorted(
            s.exec(select(VideoPipelineScene).where(
                VideoPipelineScene.run_id == run_id,
                VideoPipelineScene.product_index == product_index,
                VideoPipelineScene.video_index == video_index)).all(),
            key=lambda sc: sc.scene_index)
        scene_rows = [(sc.id, sc.scene_index, sc.status, sc.image_prompt,
                       sc.video_prompt, sc.storyboard_media_id) for sc in scenes]

    if any(not ip for (_id, _idx, _st, ip, _vp, _sb) in scene_rows):
        script = await deps.plan_script(script_brief=script_brief, scene_count=len(scene_rows))
        with get_session() as s:
            for (sid, sidx, _st, _ip, _vp, _sb), sc_def in zip(scene_rows, script):
                sc = s.get(VideoPipelineScene, sid)
                if not sc.image_prompt:
                    sc.image_prompt = sc_def["image_prompt"]
                    sc.video_prompt = sc_def["video_prompt"]
                    s.add(sc)
            s.commit()
        if video_status in ("composite_done",):
            tr.set_video_status(short_id, video_id, "scripted")
        with get_session() as s:
            scenes = sorted(
                s.exec(select(VideoPipelineScene).where(
                    VideoPipelineScene.run_id == run_id,
                    VideoPipelineScene.product_index == product_index,
                    VideoPipelineScene.video_index == video_index)).all(),
                key=lambda sc: sc.scene_index)
            scene_rows = [(sc.id, sc.scene_index, sc.status, sc.image_prompt,
                           sc.video_prompt, sc.storyboard_media_id) for sc in scenes]
    elif video_status == "composite_done":
        tr.set_video_status(short_id, video_id, "scripted")

    for sid, sidx, status, image_prompt, video_prompt, sb_mid in scene_rows:
        if _is_cancelled(short_id):
            return
        if status in ("clip_done", "merged"):
            continue
        try:
            if status in ("pending", "storyboard_running") or not sb_mid:
                tr.set_scene_status(short_id, sid, "storyboard_running")
                sb = await deps.gen_storyboard(
                    image_prompt=image_prompt, composite_media_id=composite_mid,
                    background_media_id=background_mid, project_id=project_id,
                    aspect_ratio=aspect,
                    product_index=product_index, video_index=video_index, scene_index=sidx)
                with get_session() as s:
                    sc = s.get(VideoPipelineScene, sid)
                    sc.storyboard_media_id = sb
                    s.add(sc); s.commit()
                tr.set_scene_status(short_id, sid, "storyboard_done")
            else:
                sb = sb_mid
            tr.set_scene_status(short_id, sid, "clip_running")
            clip = await deps.gen_clip(
                video_prompt=video_prompt, start_media_id=sb, project_id=project_id,
                aspect_ratio=aspect, quality=quality,
                product_index=product_index, video_index=video_index, scene_index=sidx)
            with get_session() as s:
                sc = s.get(VideoPipelineScene, sid)
                sc.clip_media_id = clip
                s.add(sc); s.commit()
            tr.set_scene_status(short_id, sid, "clip_done")
        except (StoryboardGenError, ClipGenError) as e:
            tr.set_scene_status(short_id, sid, "failed", error=str(e))

    with get_session() as s:
        scenes = s.exec(select(VideoPipelineScene).where(
            VideoPipelineScene.run_id == run_id,
            VideoPipelineScene.product_index == product_index,
            VideoPipelineScene.video_index == video_index)).all()
        v = s.get(VideoPipelineVideo, video_id)
        cur = v.status
    if all(sc.status in ("clip_done", "merged", "failed") for sc in scenes) and cur == "scripted":
        tr.set_video_status(short_id, video_id, "scenes_done")
        await _merge_video(short_id, run_id, deps, video_id, product_index, video_index,
                           crossfade_sec, audio)


async def _merge_video(short_id, run_id, deps, video_id, product_index, video_index,
                       crossfade_sec, audio):
    with get_session() as s:
        v = s.get(VideoPipelineVideo, video_id)
        if v.status == "done":
            return
        scenes = sorted(
            s.exec(select(VideoPipelineScene).where(
                VideoPipelineScene.run_id == run_id,
                VideoPipelineScene.product_index == product_index,
                VideoPipelineScene.video_index == video_index)).all(),
            key=lambda sc: sc.scene_index)
        clip_ids = [sc.clip_media_id for sc in scenes
                    if sc.status == "clip_done" and sc.clip_media_id]
        run_obj = s.get(VideoPipelineRun, run_id)
        short = run_obj.short_id

    if not clip_ids:
        tr.set_video_status(short_id, video_id, "failed", error="no clips to merge")
        return

    tr.set_video_status(short_id, video_id, "merging")
    local_clips = []
    for j, mid in enumerate(clip_ids):
        dest = storage.clip_path(short, product_index, video_index, j)
        local_clips.append(await deps.fetch_clip_to(mid, dest))
    out_path = storage.merged_path(short, product_index, video_index)
    res = await deps.merge(clips=local_clips, out_path=out_path,
                           crossfade_sec=crossfade_sec, audio=audio)
    with get_session() as s:
        v = s.get(VideoPipelineVideo, video_id)
        v.merged_local_path = res["path"]
        v.merged_url = f"/api/video-pipeline/runs/{short}/videos/{video_id}/preview"
        v.file_size_bytes = res["file_size_bytes"]
        s.add(v)
        s.commit()
    tr.set_video_status(short_id, video_id, "done")
