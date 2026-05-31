import pytest
from sqlmodel import select

from flowboard.db.session import get_session
from flowboard.db.video_pipeline_models import (
    VideoPipelineRun, VideoPipelineVideo, VideoPipelineScene,
)
from flowboard.services.video_pipeline import run_builder, orchestrator


class FakeDeps:
    """Injected generation deps — deterministic, no network."""
    def __init__(self, fail_scene=None):
        self.fail_scene = fail_scene  # (product_index, video_index, scene_index) to fail clip
        self.composite_calls = 0

    async def ensure_project(self, run):
        return "proj_fake"

    async def gen_composites(self, **k):
        self.composite_calls += 1
        n = k["variant_count"]
        return [{"media_id": f"comp{i}", "url": "u"} for i in range(n)]

    async def plan_script(self, *, script_brief, scene_count):
        return [{"image_prompt": f"ip{j}", "video_prompt": f"vp{j}"} for j in range(scene_count)]

    async def gen_storyboard(self, **k):
        return f"sb-{k['composite_media_id']}"

    async def gen_clip(self, *, product_index, video_index, scene_index, **k):
        if self.fail_scene == (product_index, video_index, scene_index):
            from flowboard.services.video_pipeline.clip_gen import ClipGenError
            raise ClipGenError("blocked")
        return f"clip-{product_index}-{video_index}-{scene_index}"

    async def fetch_clip_to(self, media_id, dest):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"FAKE"); return dest

    async def merge(self, *, clips, out_path, crossfade_sec, audio, durations=None):
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(b"FAKE")
        return {"file_size_bytes": 4, "path": str(out_path)}


def _make_run(products=1, videos=1, scenes=2):
    return run_builder.create_run(type_key="product_review", inputs={
        "character": {"source": "upload", "media_id": "c"},
        "background": {"source": "upload", "media_id": "b"},
        "products": [{"source": "upload", "media_id": f"p{i}"} for i in range(products)],
        "script_brief": "demo", "aspect_ratio": "9:16",
        "video_count": videos, "scene_count": scenes, "concurrency_cap": 2,
    })


@pytest.mark.asyncio
async def test_happy_path_all_scenes_clip_done(monkeypatch, tmp_path):
    from flowboard.services.video_pipeline import storage
    monkeypatch.setattr(storage, "STORAGE_DIR", tmp_path)
    run = _make_run(products=2, videos=2, scenes=3)
    deps = FakeDeps()
    await orchestrator.run(run.short_id, deps=deps)

    with get_session() as s:
        scenes = s.exec(select(VideoPipelineScene).where(
            VideoPipelineScene.run_id == run.id)).all()
        videos = s.exec(select(VideoPipelineVideo).where(
            VideoPipelineVideo.run_id == run.id)).all()
        run_row = s.get(VideoPipelineRun, run.id)

    assert len(scenes) == 2 * 2 * 3
    assert all(sc.status == "clip_done" for sc in scenes)
    assert all(sc.clip_media_id for sc in scenes)
    assert all(v.status == "done" for v in videos)
    assert all(v.composite_media_id for v in videos)
    assert run_row.status == "done"


@pytest.mark.asyncio
async def test_per_scene_failure_does_not_fail_run(monkeypatch, tmp_path):
    from flowboard.services.video_pipeline import storage
    monkeypatch.setattr(storage, "STORAGE_DIR", tmp_path)
    run = _make_run(products=1, videos=1, scenes=3)
    deps = FakeDeps(fail_scene=(0, 0, 1))
    await orchestrator.run(run.short_id, deps=deps)

    with get_session() as s:
        scenes = sorted(s.exec(select(VideoPipelineScene).where(
            VideoPipelineScene.run_id == run.id)).all(), key=lambda x: x.scene_index)
        run_row = s.get(VideoPipelineRun, run.id)

    assert scenes[0].status == "clip_done"
    assert scenes[1].status == "failed"
    assert scenes[2].status == "clip_done"
    assert run_row.status != "failed"


@pytest.mark.asyncio
async def test_resume_skips_completed_scenes(monkeypatch, tmp_path):
    from flowboard.services.video_pipeline import storage
    monkeypatch.setattr(storage, "STORAGE_DIR", tmp_path)
    run = _make_run(products=1, videos=1, scenes=2)
    deps = FakeDeps()
    await orchestrator.run(run.short_id, deps=deps)
    first_composites = deps.composite_calls

    # Re-run: idempotent, composites already present -> not regenerated.
    deps2 = FakeDeps()
    await orchestrator.run(run.short_id, deps=deps2)
    assert deps2.composite_calls == 0  # all videos already had composite_media_id


@pytest.mark.asyncio
async def test_cancel_stops_before_more_work(monkeypatch, tmp_path):
    from flowboard.services.video_pipeline import storage
    monkeypatch.setattr(storage, "STORAGE_DIR", tmp_path)
    run = _make_run(products=2, videos=1, scenes=2)
    with get_session() as s:
        r = s.get(VideoPipelineRun, run.id)
        r.cancelled = True
        s.add(r)
        s.commit()
    deps = FakeDeps()
    await orchestrator.run(run.short_id, deps=deps)
    with get_session() as s:
        run_row = s.get(VideoPipelineRun, run.id)
    assert run_row.status == "cancelled"
