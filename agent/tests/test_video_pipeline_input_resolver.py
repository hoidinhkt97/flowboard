import pytest

from flowboard.services.video_pipeline import input_resolver as ir


def test_aspect_ratio_mapping():
    assert ir.to_image_aspect("9:16") == "IMAGE_ASPECT_RATIO_PORTRAIT"
    assert ir.to_image_aspect("16:9") == "IMAGE_ASPECT_RATIO_LANDSCAPE"
    assert ir.to_image_aspect("1:1") == "IMAGE_ASPECT_RATIO_SQUARE"
    assert ir.to_image_aspect("weird") == "IMAGE_ASPECT_RATIO_LANDSCAPE"


@pytest.mark.asyncio
async def test_resolve_ai_gen_calls_llm_then_gen_image():
    calls = {}

    async def fake_llm(provider, user_prompt, *, system_prompt=None, attachments=None, timeout=90.0):
        calls["llm_prompt"] = user_prompt
        return "A cinematic full-body portrait of a friendly host, studio lighting."

    class FakeSDK:
        async def gen_image(self, prompt, project_id, aspect_ratio, ref_media_ids, variant_count, paygate_tier=None):
            calls["gen_prompt"] = prompt
            calls["variant_count"] = variant_count
            return {"media_ids": ["m1", "m2", "m3", "m4"],
                    "media_entries": [{"media_id": f"m{i}", "url": f"http://x/{i}"} for i in range(1, 5)]}

    out = await ir.resolve_ai_gen(
        description="thân thiện, áo thun trắng",
        project_id="proj_1",
        aspect_ratio="9:16",
        variant_count=4,
        llm_runner=fake_llm,
        sdk=FakeSDK(),
    )
    assert out["media_ids"] == ["m1", "m2", "m3", "m4"]
    assert len(out["media_entries"]) == 4
    assert "friendly host" in calls["gen_prompt"]
    assert calls["variant_count"] == 4


@pytest.mark.asyncio
async def test_resolve_ai_gen_surfaces_gen_error():
    async def fake_llm(*a, **k):
        return "prompt"

    class FailSDK:
        async def gen_image(self, **k):
            return {"error": "rate_limited"}

    with pytest.raises(ir.InputResolveError):
        await ir.resolve_ai_gen(description="x", project_id="p", aspect_ratio="1:1",
                                variant_count=4, llm_runner=fake_llm, sdk=FailSDK())
