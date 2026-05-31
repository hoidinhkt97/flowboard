import pytest
from sqlmodel import select

from flowboard.db.session import get_session
from flowboard.db.video_pipeline_models import VideoPipelineScene, VideoPipelineRun
from flowboard.services.video_pipeline import run_builder, transitions


def _make_run():
    return run_builder.create_run(type_key="product_review", inputs={
        "character": {"source": "upload", "media_id": "c"},
        "background": {"source": "upload", "media_id": "b"},
        "products": [{"source": "upload", "media_id": "p0"}],
        "script_brief": "x", "aspect_ratio": "9:16",
        "video_count": 1, "scene_count": 1,
    })


def test_set_scene_status_valid(monkeypatch, tmp_path):
    from flowboard.services.video_pipeline import storage
    monkeypatch.setattr(storage, "STORAGE_DIR", tmp_path)
    run = _make_run()
    with get_session() as s:
        sc = s.exec(select(VideoPipelineScene).where(
            VideoPipelineScene.run_id == run.id)).first()
        sid = sc.id

    transitions.set_scene_status(run.short_id, sid, "storyboard_running")
    with get_session() as s:
        sc = s.get(VideoPipelineScene, sid)
        assert sc.status == "storyboard_running"


def test_set_scene_status_invalid_raises(monkeypatch, tmp_path):
    from flowboard.services.video_pipeline import storage
    monkeypatch.setattr(storage, "STORAGE_DIR", tmp_path)
    run = _make_run()
    with get_session() as s:
        sc = s.exec(select(VideoPipelineScene).where(
            VideoPipelineScene.run_id == run.id)).first()
        sid = sc.id
    with pytest.raises(transitions.InvalidTransition):
        transitions.set_scene_status(run.short_id, sid, "merged")  # pending->merged illegal


def test_set_run_status_writes_manifest(monkeypatch, tmp_path):
    from flowboard.services.video_pipeline import storage
    monkeypatch.setattr(storage, "STORAGE_DIR", tmp_path)
    run = _make_run()
    transitions.set_run_status(run.short_id, "resolving")
    manifest = storage.read_manifest(run.short_id)
    assert manifest["status"] == "resolving"
