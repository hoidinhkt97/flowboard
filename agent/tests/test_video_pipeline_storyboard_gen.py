import pytest

from flowboard.services.video_pipeline import storyboard_gen as sg


@pytest.mark.asyncio
async def test_generate_storyboard_uses_composite_and_background_refs():
    seen = {}

    class FakeSDK:
        async def gen_image(self, prompt, project_id, aspect_ratio, ref_media_ids, variant_count, paygate_tier=None, image_model=None):
            seen["refs"] = ref_media_ids
            seen["count"] = variant_count
            seen["prompt"] = prompt
            seen["paygate_tier"] = paygate_tier
            return {"media_entries": [{"media_id": "sb0", "url": "u"}], "media_ids": ["sb0"]}

    mid = await sg.generate_storyboard(
        image_prompt="wide shot", composite_media_id="comp", background_media_id="bg",
        project_id="proj", aspect_ratio="9:16", sdk=FakeSDK(), ingest=lambda e: None)

    assert seen["refs"] == ["comp", "bg"]
    assert seen["count"] == 1
    assert seen["prompt"] == "wide shot"
    assert seen["paygate_tier"]  # resolved + passed
    assert mid == "sb0"


@pytest.mark.asyncio
async def test_generate_storyboard_error_raises():
    class FailSDK:
        async def gen_image(self, **k):
            return {"error": "filtered"}

    with pytest.raises(sg.StoryboardGenError):
        await sg.generate_storyboard(
            image_prompt="x", composite_media_id="c", background_media_id="b",
            project_id="p", aspect_ratio="1:1", sdk=FailSDK(), ingest=lambda e: None)


@pytest.mark.asyncio
async def test_generate_storyboard_raises_when_no_paygate_tier():
    from flowboard.services.flow_client import flow_client
    saved = flow_client._paygate_tier
    flow_client._paygate_tier = None
    try:
        class NeverCalledSDK:
            async def gen_image(self, **k):
                raise AssertionError("gen_image must not be called without a tier")
        with pytest.raises(sg.StoryboardGenError):
            await sg.generate_storyboard(
                image_prompt="x", composite_media_id="c", background_media_id="b",
                project_id="p", aspect_ratio="1:1", paygate_tier=None,
                sdk=NeverCalledSDK(), ingest=lambda e: None)
    finally:
        flow_client._paygate_tier = saved
