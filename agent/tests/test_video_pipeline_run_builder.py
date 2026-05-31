from sqlmodel import select

from flowboard.db.session import get_session
from flowboard.db.video_pipeline_models import (
    VideoPipelineRun, VideoPipelineProduct, VideoPipelineVideo, VideoPipelineScene,
)
from flowboard.services.video_pipeline import run_builder


def _sample_inputs():
    return {
        "character": {"source": "upload", "media_id": "char_m"},
        "background": {"source": "upload", "media_id": "bg_m"},
        "products": [
            {"source": "upload", "media_id": "p0_m"},
            {"source": "upload", "media_id": "p1_m"},
        ],
        "script_brief": "Giới thiệu sản phẩm vui nhộn",
        "aspect_ratio": "9:16",
        "video_count": 2,
        "scene_count": 3,
        "quality": "standard",
        "crossfade_sec": 0.4,
        "audio_enabled": True,
        "concurrency_cap": 4,
    }


def test_create_run_builds_full_tree():
    run = run_builder.create_run(type_key="product_review", inputs=_sample_inputs())
    assert run.short_id.startswith("vpr_")
    assert run.status == "pending"

    with get_session() as s:
        rid = run.id
        products = s.exec(select(VideoPipelineProduct).where(
            VideoPipelineProduct.run_id == rid)).all()
        videos = s.exec(select(VideoPipelineVideo).where(
            VideoPipelineVideo.run_id == rid)).all()
        scenes = s.exec(select(VideoPipelineScene).where(
            VideoPipelineScene.run_id == rid)).all()

    assert len(products) == 2
    assert len(videos) == 2 * 2
    assert len(scenes) == 2 * 2 * 3


def test_create_run_requires_at_least_one_product():
    import pytest
    bad = _sample_inputs()
    bad["products"] = []
    with pytest.raises(run_builder.RunValidationError):
        run_builder.create_run(type_key="product_review", inputs=bad)


def test_create_run_rejects_unknown_type():
    import pytest
    with pytest.raises(run_builder.RunValidationError):
        run_builder.create_run(type_key="nope", inputs=_sample_inputs())


def test_video_count_clamped_1_to_4():
    import pytest
    bad = _sample_inputs()
    bad["video_count"] = 9
    with pytest.raises(run_builder.RunValidationError):
        run_builder.create_run(type_key="product_review", inputs=bad)
