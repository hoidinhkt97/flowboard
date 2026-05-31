from sqlmodel import select

from flowboard.db.session import get_session
from flowboard.db.video_pipeline_models import (
    VideoPipelineRun, VideoPipelineVideo, VideoPipelineScene,
)
from flowboard.services.video_pipeline import run_builder
from flowboard.routes import video_pipeline as vp_routes


def _seed(client, monkeypatch, tmp_path):
    from flowboard.services.video_pipeline import storage
    monkeypatch.setattr(storage, "STORAGE_DIR", tmp_path)
    # no-op orchestrator so regen-relaunch doesn't do real work
    async def noop(short_id, **k): return None
    monkeypatch.setattr(vp_routes, "_orchestrator_run", noop)
    run = run_builder.create_run(type_key="product_review", inputs={
        "character": {"source": "upload", "media_id": "c"},
        "background": {"source": "upload", "media_id": "b"},
        "products": [{"source": "upload", "media_id": "p0"}],
        "script_brief": "x", "aspect_ratio": "9:16",
        "video_count": 1, "scene_count": 1})
    with get_session() as s:
        v = s.exec(select(VideoPipelineVideo).where(
            VideoPipelineVideo.run_id == run.id)).first()
        sc = s.exec(select(VideoPipelineScene).where(
            VideoPipelineScene.run_id == run.id)).first()
        v.status = "done"; v.composite_media_id = "comp"; s.add(v)
        sc.status = "clip_done"; sc.storyboard_media_id = "sb"; sc.clip_media_id = "cl"
        sc.image_prompt = "ip"; sc.video_prompt = "vp"; s.add(sc)
        s.commit()
        return run.short_id, v.id, sc.id


def test_cancel_sets_cancelled(client, monkeypatch, tmp_path):
    sid, vid, scid = _seed(client, monkeypatch, tmp_path)
    r = client.post(f"/api/video-pipeline/runs/{sid}/cancel")
    assert r.status_code == 200
    with get_session() as s:
        run = s.exec(select(VideoPipelineRun).where(
            VideoPipelineRun.short_id == sid)).first()
    assert run.cancelled is True


def test_patch_scene_prompt(client, monkeypatch, tmp_path):
    sid, vid, scid = _seed(client, monkeypatch, tmp_path)
    r = client.patch(f"/api/video-pipeline/runs/{sid}/scenes/{scid}",
                     json={"image_prompt": "new ip", "video_prompt": "new vp"})
    assert r.status_code == 200
    with get_session() as s:
        sc = s.get(VideoPipelineScene, scid)
    assert sc.image_prompt == "new ip"


def test_patch_scene_running_returns_409(client, monkeypatch, tmp_path):
    sid, vid, scid = _seed(client, monkeypatch, tmp_path)
    with get_session() as s:
        sc = s.get(VideoPipelineScene, scid)
        sc.status = "clip_running"; s.add(sc); s.commit()
    r = client.patch(f"/api/video-pipeline/runs/{sid}/scenes/{scid}",
                     json={"image_prompt": "x"})
    assert r.status_code == 409


def test_regen_clip_route(client, monkeypatch, tmp_path):
    sid, vid, scid = _seed(client, monkeypatch, tmp_path)
    r = client.post(f"/api/video-pipeline/runs/{sid}/scenes/{scid}/regen-clip")
    assert r.status_code == 202
    with get_session() as s:
        sc = s.get(VideoPipelineScene, scid)
    assert sc.clip_media_id is None


def test_regen_clip_running_returns_409(client, monkeypatch, tmp_path):
    sid, vid, scid = _seed(client, monkeypatch, tmp_path)
    with get_session() as s:
        sc = s.get(VideoPipelineScene, scid)
        sc.status = "clip_running"; s.add(sc); s.commit()
    r = client.post(f"/api/video-pipeline/runs/{sid}/scenes/{scid}/regen-clip")
    assert r.status_code == 409


def test_regen_composite_route(client, monkeypatch, tmp_path):
    sid, vid, scid = _seed(client, monkeypatch, tmp_path)
    r = client.post(f"/api/video-pipeline/runs/{sid}/videos/{vid}/regen-composite")
    assert r.status_code == 202
    with get_session() as s:
        v = s.get(VideoPipelineVideo, vid)
    assert v.composite_media_id is None
