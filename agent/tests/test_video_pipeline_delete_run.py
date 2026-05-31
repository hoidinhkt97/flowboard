from sqlmodel import select

from flowboard.db.session import get_session
from flowboard.db.video_pipeline_models import VideoPipelineRun, VideoPipelineScene
from flowboard.services.video_pipeline import run_builder, storage


def _inputs():
    return {
        "character": {"source": "upload", "media_id": "c"},
        "background": {"source": "upload", "media_id": "b"},
        "products": [{"source": "upload", "media_id": "p0"}],
        "script_brief": "x", "aspect_ratio": "9:16",
        "video_count": 1, "scene_count": 1,
    }


def test_delete_run_removes_rows_and_files(client, monkeypatch, tmp_path):
    monkeypatch.setattr(storage, "STORAGE_DIR", tmp_path)
    run = run_builder.create_run(type_key="product_review", inputs=_inputs())
    storage.ensure_run_dirs(run.short_id)
    base = storage.run_dir(run.short_id)
    assert base.exists()

    r = client.delete(f"/api/video-pipeline/runs/{run.short_id}")
    assert r.status_code == 204

    with get_session() as s:
        gone = s.exec(select(VideoPipelineRun).where(
            VideoPipelineRun.short_id == run.short_id)).first()
        scenes = s.exec(select(VideoPipelineScene).where(
            VideoPipelineScene.run_id == run.id)).all()
    assert gone is None
    assert list(scenes) == []
    assert not base.exists()


def test_delete_missing_run_404(client):
    r = client.delete("/api/video-pipeline/runs/vpr_nope")
    assert r.status_code == 404
