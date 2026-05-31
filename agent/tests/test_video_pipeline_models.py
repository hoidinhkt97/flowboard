from datetime import datetime

from sqlmodel import select

from flowboard.db.session import get_session
from flowboard.db.video_pipeline_models import (
    VideoPipelineTemplate,
    VideoPipelineRun,
    VideoPipelineProduct,
    VideoPipelineVideo,
    VideoPipelineScene,
)


def test_run_roundtrip_with_json_inputs():
    with get_session() as s:
        run = VideoPipelineRun(
            short_id="vpr_test1",
            type_key="product_review",
            inputs={"aspect_ratio": "9:16", "video_count": 2, "scene_count": 3},
        )
        s.add(run)
        s.commit()
        s.refresh(run)
        assert run.id is not None
        assert run.status == "pending"
        assert isinstance(run.created_at, datetime)

    with get_session() as s:
        loaded = s.exec(
            select(VideoPipelineRun).where(VideoPipelineRun.short_id == "vpr_test1")
        ).one()
        assert loaded.inputs["aspect_ratio"] == "9:16"
        assert loaded.inputs["video_count"] == 2


def test_unique_constraints_enforced():
    import pytest
    from sqlalchemy.exc import IntegrityError

    with get_session() as s:
        s.add(VideoPipelineRun(short_id="vpr_dup"))
        s.commit()
    with get_session() as s:
        s.add(VideoPipelineRun(short_id="vpr_dup"))
        with pytest.raises(IntegrityError):
            s.commit()


def test_child_rows_and_composite_uniqueness():
    import pytest
    from sqlalchemy.exc import IntegrityError

    with get_session() as s:
        run = VideoPipelineRun(short_id="vpr_kids")
        s.add(run)
        s.commit()
        s.refresh(run)
        rid = run.id

    with get_session() as s:
        s.add(VideoPipelineVideo(run_id=rid, product_index=0, video_index=0))
        s.commit()
    with get_session() as s:
        s.add(VideoPipelineVideo(run_id=rid, product_index=0, video_index=0))
        with pytest.raises(IntegrityError):
            s.commit()


def test_template_builtin_flag_defaults():
    with get_session() as s:
        t = VideoPipelineTemplate(name="Default", type_key="product_review",
                                  params={"scene_count": 3})
        s.add(t)
        s.commit()
        s.refresh(t)
        assert t.is_builtin is False
        assert t.position == 0
        assert t.params["scene_count"] == 3
