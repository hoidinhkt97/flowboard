import pytest
from sqlmodel import select

from flowboard.db.session import get_session
from flowboard.db.video_pipeline_models import VideoPipelineVideo, VideoPipelineScene
from flowboard.services.video_pipeline import run_builder, regen, storage


def _seed_done_video(monkeypatch, tmp_path):
    monkeypatch.setattr(storage, "STORAGE_DIR", tmp_path)
    run = run_builder.create_run(type_key="product_review", inputs={
        "character": {"source": "upload", "media_id": "c"},
        "background": {"source": "upload", "media_id": "b"},
        "products": [{"source": "upload", "media_id": "p0"}],
        "script_brief": "x", "aspect_ratio": "9:16",
        "video_count": 1, "scene_count": 2})
    with get_session() as s:
        v = s.exec(select(VideoPipelineVideo).where(
            VideoPipelineVideo.run_id == run.id)).first()
        v.status = "done"; v.composite_media_id = "comp"; v.merged_local_path = "x.mp4"
        v.merged_url = "/preview"; s.add(v)
        scenes = s.exec(select(VideoPipelineScene).where(
            VideoPipelineScene.run_id == run.id)).all()
        for sc in scenes:
            sc.status = "clip_done"; sc.storyboard_media_id = "sb"; sc.clip_media_id = "cl"
            s.add(sc)
        s.commit()
        return run, v.id, [sc.id for sc in scenes]


def test_regen_clip_keeps_storyboard(monkeypatch, tmp_path):
    run, vid, scene_ids = _seed_done_video(monkeypatch, tmp_path)
    regen.reset_for_clip(run.short_id, scene_ids[0])
    with get_session() as s:
        sc = s.get(VideoPipelineScene, scene_ids[0])
        v = s.get(VideoPipelineVideo, vid)
    assert sc.clip_media_id is None
    assert sc.storyboard_media_id == "sb"      # kept
    assert sc.status == "storyboard_done"
    assert v.merged_local_path is None          # merged invalidated
    assert v.status in ("scripted", "scenes_done")


def test_regen_storyboard_clears_clip_and_storyboard(monkeypatch, tmp_path):
    run, vid, scene_ids = _seed_done_video(monkeypatch, tmp_path)
    regen.reset_for_storyboard(run.short_id, scene_ids[0])
    with get_session() as s:
        sc = s.get(VideoPipelineScene, scene_ids[0])
    assert sc.storyboard_media_id is None
    assert sc.clip_media_id is None
    assert sc.status == "pending"


def test_regen_composite_resets_all_scenes(monkeypatch, tmp_path):
    run, vid, scene_ids = _seed_done_video(monkeypatch, tmp_path)
    regen.reset_for_composite(run.short_id, vid)
    with get_session() as s:
        v = s.get(VideoPipelineVideo, vid)
        scenes = s.exec(select(VideoPipelineScene).where(
            VideoPipelineScene.run_id == run.id)).all()
    assert v.composite_media_id is None
    assert v.status == "pending"
    assert all(sc.status == "pending" and sc.storyboard_media_id is None
               and sc.clip_media_id is None for sc in scenes)


def test_regen_blocks_when_in_flight(monkeypatch, tmp_path):
    run, vid, scene_ids = _seed_done_video(monkeypatch, tmp_path)
    with get_session() as s:
        sc = s.get(VideoPipelineScene, scene_ids[0])
        sc.status = "clip_running"; s.add(sc); s.commit()
    with pytest.raises(regen.RegenConflict):
        regen.reset_for_clip(run.short_id, scene_ids[0])
