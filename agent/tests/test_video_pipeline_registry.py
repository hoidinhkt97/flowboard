from flowboard.services.video_pipeline.types import registry


def test_product_review_registered():
    t = registry.get("product_review")
    assert t.key == "product_review"
    assert t.label
    assert "character" in t.input_schema
    assert "products" in t.input_schema
    assert "background" in t.input_schema


def test_list_types_returns_serializable():
    items = registry.list_types()
    assert any(i["key"] == "product_review" for i in items)
    for i in items:
        assert set(i.keys()) >= {"key", "label", "input_schema"}


def test_unknown_type_raises():
    import pytest
    with pytest.raises(KeyError):
        registry.get("does_not_exist")


def test_build_video_steps_scene_count():
    t = registry.get("product_review")
    steps = t.build_video_steps({"scene_count": 2})
    kinds = [s.kind for s in steps]
    assert kinds[0] == "composite"
    assert kinds[1] == "script"
    assert kinds.count("storyboard") == 2
    assert kinds.count("clip") == 2
    assert kinds[-1] == "merge"
