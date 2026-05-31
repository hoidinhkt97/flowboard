from pathlib import Path

from flowboard.services.video_pipeline import storage


def test_run_dir_under_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "STORAGE_DIR", tmp_path)
    d = storage.run_dir("vpr_abc")
    assert d == tmp_path / "video_pipeline" / "vpr_abc"


def test_composite_path_naming(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "STORAGE_DIR", tmp_path)
    p = storage.composite_path("vpr_abc", product_index=1, video_index=2)
    assert p.name == "p1-v2.png"
    assert "composites" in p.parts


def test_storyboard_and_clip_and_merged_paths(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "STORAGE_DIR", tmp_path)
    sb = storage.storyboard_path("vpr_abc", 0, 1, 2)
    assert sb.name == "p0-v1-s2.png" and "storyboards" in sb.parts
    clip = storage.clip_path("vpr_abc", 0, 1, 2)
    assert clip.name == "p0-v1-s2.mp4" and "clips" in clip.parts
    merged = storage.merged_path("vpr_abc", 0, 1)
    assert merged.name == "p0-v1.mp4" and "merged" in merged.parts


def test_ensure_run_dirs_creates_tree(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "STORAGE_DIR", tmp_path)
    storage.ensure_run_dirs("vpr_abc")
    base = tmp_path / "video_pipeline" / "vpr_abc"
    for sub in ("composites", "storyboards", "clips", "merged"):
        assert (base / sub).is_dir()


def test_manifest_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "STORAGE_DIR", tmp_path)
    storage.ensure_run_dirs("vpr_abc")
    payload = {"run": {"short_id": "vpr_abc", "status": "generating"}, "videos": []}
    storage.write_manifest("vpr_abc", payload)
    loaded = storage.read_manifest("vpr_abc")
    assert loaded == payload


def test_read_manifest_missing_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "STORAGE_DIR", tmp_path)
    assert storage.read_manifest("nope") is None
