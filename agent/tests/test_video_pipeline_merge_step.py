import pytest
from pathlib import Path

from sqlmodel import select

from flowboard.db.session import get_session
from flowboard.db.video_pipeline_models import VideoPipelineRun, VideoPipelineVideo
from flowboard.services.video_pipeline import run_builder, orchestrator, storage


class MergeFakeDeps:
    async def ensure_project(self, run): return "proj"
    async def gen_composites(self, **k):
        return [{"media_id": f"comp{i}", "url": "u"} for i in range(k["variant_count"])]
    async def plan_script(self, *, script_brief, scene_count):
        return [{"image_prompt": f"ip{j}", "video_prompt": f"vp{j}"} for j in range(scene_count)]
    async def gen_storyboard(self, **k): return f"sb-{k['scene_index']}"
    async def gen_clip(self, *, product_index, video_index, scene_index, **k):
        return f"clip-{scene_index}"
    async def fetch_clip_to(self, media_id, dest: Path):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"CLIP"); return dest
    async def merge(self, *, clips, out_path, crossfade_sec, audio, durations=None):
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(b"MERGED")
        return {"file_size_bytes": out_path.stat().st_size, "path": str(out_path)}


@pytest.mark.asyncio
async def test_merge_step_completes_run(monkeypatch, tmp_path):
    monkeypatch.setattr(storage, "STORAGE_DIR", tmp_path)
    run = run_builder.create_run(type_key="product_review", inputs={
        "character": {"source": "upload", "media_id": "c"},
        "background": {"source": "upload", "media_id": "b"},
        "products": [{"source": "upload", "media_id": "p0"}],
        "script_brief": "x", "aspect_ratio": "9:16",
        "video_count": 1, "scene_count": 2, "crossfade_sec": 0.0})
    await orchestrator.run(run.short_id, deps=MergeFakeDeps())

    with get_session() as s:
        v = s.exec(select(VideoPipelineVideo).where(
            VideoPipelineVideo.run_id == run.id)).first()
        run_row = s.get(VideoPipelineRun, run.id)
    assert v.status == "done"
    assert v.merged_local_path and Path(v.merged_local_path).exists()
    assert v.merged_url
    assert run_row.status == "done"
