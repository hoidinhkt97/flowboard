from flowboard.services.video_pipeline import run_builder, serializers


def _inputs():
    return {
        "character": {"source": "upload", "media_id": "char_m"},
        "background": {"source": "upload", "media_id": "bg_m"},
        "products": [{"source": "upload", "media_id": "p0_m"}],
        "script_brief": "x", "aspect_ratio": "9:16",
        "video_count": 1, "scene_count": 2,
    }


def test_serialize_run_nested_shape():
    run = run_builder.create_run(type_key="product_review", inputs=_inputs())
    dto = serializers.serialize_run(run.short_id)
    assert dto["short_id"] == run.short_id
    assert dto["status"] == "pending"
    assert len(dto["products"]) == 1
    prod = dto["products"][0]
    assert len(prod["videos"]) == 1
    assert len(prod["videos"][0]["scenes"]) == 2
    assert dto["progress"]["clips_total"] == 2
    assert dto["progress"]["clips_done"] == 0


def test_serialize_missing_returns_none():
    assert serializers.serialize_run("vpr_missing") is None
