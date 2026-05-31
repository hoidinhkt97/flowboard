import pytest

from flowboard.services.video_pipeline import clip_gen as cg


@pytest.mark.asyncio
async def test_clip_dispatch_then_poll_success():
    polls = {"n": 0}

    class FakeSDK:
        async def gen_video(self, prompt, project_id, start_media_id, aspect_ratio, video_quality=None, paygate_tier=None):
            assert start_media_id == "sb0"
            assert paygate_tier
            return {"operation_names": ["op1"]}

        async def check_async(self, operation_names, workflows=None):
            polls["n"] += 1
            if polls["n"] < 2:
                return {"operations": [{"name": "op1", "done": False}]}
            return {"operations": [{"name": "op1", "done": True,
                                    "media_entries": [{"media_id": "clip0", "url": "u"}]}]}

    async def no_sleep(_):
        return None

    ingested = {}

    def ingest(entries):
        ingested["entries"] = entries

    mid = await cg.generate_clip(
        video_prompt="dolly in", start_media_id="sb0", project_id="proj",
        aspect_ratio="9:16", quality="standard",
        sdk=FakeSDK(), sleep=no_sleep, ingest=ingest)
    assert mid == "clip0"
    assert polls["n"] == 2
    assert ingested["entries"]


@pytest.mark.asyncio
async def test_clip_dispatch_error_raises():
    class FailSDK:
        async def gen_video(self, **k):
            return {"error": "quota"}

    with pytest.raises(cg.ClipGenError):
        await cg.generate_clip(video_prompt="x", start_media_id="s", project_id="p",
                               aspect_ratio="1:1", quality="fast",
                               sdk=FailSDK(), sleep=None, ingest=lambda e: None)


@pytest.mark.asyncio
async def test_clip_per_op_error_raises():
    class FilterSDK:
        async def gen_video(self, **k):
            return {"operation_names": ["op1"]}

        async def check_async(self, operation_names, workflows=None):
            return {"operations": [{"name": "op1", "done": True, "error": "UNSAFE_GENERATION"}]}

    async def no_sleep(_):
        return None

    with pytest.raises(cg.ClipGenError):
        await cg.generate_clip(video_prompt="x", start_media_id="s", project_id="p",
                               aspect_ratio="1:1", quality="fast",
                               sdk=FilterSDK(), sleep=no_sleep, ingest=lambda e: None)


@pytest.mark.asyncio
async def test_clip_timeout_raises():
    class StuckSDK:
        async def gen_video(self, **k):
            return {"operation_names": ["op1"]}

        async def check_async(self, operation_names, workflows=None):
            return {"operations": [{"name": "op1", "done": False}]}

    async def no_sleep(_):
        return None

    with pytest.raises(cg.ClipGenError):
        await cg.generate_clip(video_prompt="x", start_media_id="s", project_id="p",
                               aspect_ratio="1:1", quality="fast", max_cycles=3,
                               sdk=StuckSDK(), sleep=no_sleep, ingest=lambda e: None)


@pytest.mark.asyncio
async def test_clip_raises_when_no_paygate_tier():
    from flowboard.services.flow_client import flow_client
    saved = flow_client._paygate_tier
    flow_client._paygate_tier = None
    try:
        class NeverCalledSDK:
            async def gen_video(self, **k):
                raise AssertionError("gen_video must not be called without tier")

        async def no_sleep(_):
            return None

        with pytest.raises(cg.ClipGenError):
            await cg.generate_clip(video_prompt="x", start_media_id="s", project_id="p",
                                   aspect_ratio="1:1", quality="fast", paygate_tier=None,
                                   sdk=NeverCalledSDK(), sleep=no_sleep, ingest=lambda e: None)
    finally:
        flow_client._paygate_tier = saved
