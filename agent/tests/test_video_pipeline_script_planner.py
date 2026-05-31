import json
import pytest

from flowboard.services.video_pipeline import script_planner as sp


def _valid_scenes(n):
    return json.dumps({"scenes": [
        {"image_prompt": f"compose scene {i}", "video_prompt": f"motion {i}"}
        for i in range(n)
    ]})


@pytest.mark.asyncio
async def test_plan_returns_validated_scenes():
    async def fake_llm(feature, user_prompt, *, system_prompt=None, attachments=None, timeout=90.0):
        return _valid_scenes(3)

    scenes = await sp.plan_script(script_brief="demo", scene_count=3, llm_runner=fake_llm)
    assert len(scenes) == 3
    assert scenes[0]["image_prompt"]
    assert scenes[0]["video_prompt"]


@pytest.mark.asyncio
async def test_plan_extracts_json_from_codefence():
    async def fake_llm(*a, **k):
        return "```json\n" + _valid_scenes(2) + "\n```"

    scenes = await sp.plan_script(script_brief="x", scene_count=2, llm_runner=fake_llm)
    assert len(scenes) == 2


@pytest.mark.asyncio
async def test_plan_reprompts_on_invalid_then_succeeds():
    calls = {"n": 0}

    async def flaky_llm(*a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            return "not json at all"
        return _valid_scenes(2)

    scenes = await sp.plan_script(script_brief="x", scene_count=2,
                                  llm_runner=flaky_llm, max_retries=2)
    assert len(scenes) == 2
    assert calls["n"] == 2  # retried once


@pytest.mark.asyncio
async def test_plan_raises_after_exhausting_retries():
    async def bad_llm(*a, **k):
        return "never valid"

    with pytest.raises(sp.ScriptPlanError):
        await sp.plan_script(script_brief="x", scene_count=2,
                             llm_runner=bad_llm, max_retries=2)


@pytest.mark.asyncio
async def test_plan_rejects_wrong_scene_count():
    async def short_llm(*a, **k):
        return _valid_scenes(1)  # asked for 3

    with pytest.raises(sp.ScriptPlanError):
        await sp.plan_script(script_brief="x", scene_count=3,
                             llm_runner=short_llm, max_retries=1)


@pytest.mark.asyncio
async def test_plan_calls_llm_with_planner_feature():
    # Guards the load-bearing correction: run_llm's first arg is a FEATURE
    # ("planner"), not a provider ("claude" would raise LLMError in prod).
    seen = {}

    async def fake_llm(feature, user_prompt, *, system_prompt=None, attachments=None, timeout=90.0):
        seen["feature"] = feature
        return _valid_scenes(2)

    await sp.plan_script(script_brief="x", scene_count=2, llm_runner=fake_llm)
    assert seen["feature"] == "planner"
