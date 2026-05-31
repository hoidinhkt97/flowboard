import pytest

from flowboard.services.video_pipeline import composite_gen as cg


@pytest.mark.asyncio
async def test_generate_composites_passes_refs_and_count():
    seen = {}

    class FakeSDK:
        async def gen_image(self, prompt, project_id, aspect_ratio, ref_media_ids, variant_count, paygate_tier=None):
            seen["refs"] = ref_media_ids
            seen["count"] = variant_count
            seen["aspect"] = aspect_ratio
            seen["paygate_tier"] = paygate_tier
            return {"media_ids": ["c0", "c1"],
                    "media_entries": [{"media_id": "c0", "url": "u0"},
                                      {"media_id": "c1", "url": "u1"}]}

    ingested = {}
    def fake_ingest(entries):
        ingested["entries"] = entries

    out = await cg.generate_composites(
        character_media_id="char", product_media_id="prod",
        project_id="proj", aspect_ratio="9:16", variant_count=2,
        script_brief="vui nhộn", sdk=FakeSDK(), ingest=fake_ingest)

    assert seen["refs"] == ["char", "prod"]
    assert seen["count"] == 2
    assert seen["aspect"] == "IMAGE_ASPECT_RATIO_PORTRAIT"
    assert seen["paygate_tier"]  # resolved + passed (PAYGATE_TIER_ONE from conftest)
    assert [e["media_id"] for e in out] == ["c0", "c1"]
    assert ingested["entries"]  # persisted for /media serving


@pytest.mark.asyncio
async def test_generate_composites_raises_on_error():
    class FailSDK:
        async def gen_image(self, **k):
            return {"error": "blocked"}

    with pytest.raises(cg.CompositeGenError):
        await cg.generate_composites(
            character_media_id="c", product_media_id="p", project_id="x",
            aspect_ratio="1:1", variant_count=1, script_brief="",
            sdk=FailSDK(), ingest=lambda e: None)


@pytest.mark.asyncio
async def test_generate_composites_raises_when_fewer_than_requested():
    class ShortSDK:
        async def gen_image(self, **k):
            return {"media_ids": ["only0"], "media_entries": [{"media_id": "only0", "url": "u"}]}

    with pytest.raises(cg.CompositeGenError):
        await cg.generate_composites(
            character_media_id="c", product_media_id="p", project_id="x",
            aspect_ratio="1:1", variant_count=3, script_brief="",
            sdk=ShortSDK(), ingest=lambda e: None)


@pytest.mark.asyncio
async def test_generate_composites_raises_when_no_paygate_tier(monkeypatch):
    from flowboard.services.flow_client import flow_client
    saved = flow_client._paygate_tier
    flow_client._paygate_tier = None
    try:
        class NeverCalledSDK:
            async def gen_image(self, **k):
                raise AssertionError("gen_image must not be called without a tier")
        with pytest.raises(cg.CompositeGenError):
            await cg.generate_composites(
                character_media_id="c", product_media_id="p", project_id="x",
                aspect_ratio="1:1", variant_count=1, script_brief="",
                paygate_tier=None, sdk=NeverCalledSDK(), ingest=lambda e: None)
    finally:
        flow_client._paygate_tier = saved
