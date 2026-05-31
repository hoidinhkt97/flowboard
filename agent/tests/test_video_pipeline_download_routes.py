import zipfile
import io

from sqlmodel import select

from flowboard.db.session import get_session
from flowboard.db.video_pipeline_models import VideoPipelineVideo
from flowboard.services.video_pipeline import run_builder, storage


def _run_with_merged(monkeypatch, tmp_path):
    monkeypatch.setattr(storage, "STORAGE_DIR", tmp_path)
    run = run_builder.create_run(type_key="product_review", inputs={
        "character": {"source": "upload", "media_id": "c"},
        "background": {"source": "upload", "media_id": "b"},
        "products": [{"source": "upload", "media_id": "p0"}],
        "script_brief": "x", "aspect_ratio": "9:16",
        "video_count": 1, "scene_count": 1})
    with get_session() as s:
        v = s.exec(select(VideoPipelineVideo).where(
            VideoPipelineVideo.run_id == run.id)).first()
        vid = v.id
        mp = storage.merged_path(run.short_id, 0, 0)
        mp.parent.mkdir(parents=True, exist_ok=True)
        mp.write_bytes(b"MP4DATA")
        v.merged_local_path = str(mp)
        v.product_index = 0
        v.video_index = 0
        v.status = "done"
        s.add(v); s.commit()
    return run.short_id, vid


def test_preview_streams_inline(client, monkeypatch, tmp_path):
    sid, vid = _run_with_merged(monkeypatch, tmp_path)
    r = client.get(f"/api/video-pipeline/runs/{sid}/videos/{vid}/preview")
    assert r.status_code == 200
    assert r.content == b"MP4DATA"


def test_download_is_attachment(client, monkeypatch, tmp_path):
    sid, vid = _run_with_merged(monkeypatch, tmp_path)
    r = client.get(f"/api/video-pipeline/runs/{sid}/videos/{vid}/download")
    assert r.status_code == 200
    assert "attachment" in r.headers.get("content-disposition", "")


def test_download_all_zip(client, monkeypatch, tmp_path):
    sid, vid = _run_with_merged(monkeypatch, tmp_path)
    r = client.get(f"/api/video-pipeline/runs/{sid}/download-all.zip")
    assert r.status_code == 200
    zf = zipfile.ZipFile(io.BytesIO(r.content))
    assert len(zf.namelist()) == 1


def test_preview_missing_video_404(client, monkeypatch, tmp_path):
    sid, _ = _run_with_merged(monkeypatch, tmp_path)
    r = client.get(f"/api/video-pipeline/runs/{sid}/videos/99999/preview")
    assert r.status_code == 404
