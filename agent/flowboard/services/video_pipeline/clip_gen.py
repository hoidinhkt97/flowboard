"""Render one video clip from a storyboard image via async i2v workflow."""
from __future__ import annotations

import asyncio
from typing import Any, Callable, Optional

from flowboard.services.flow_sdk import get_flow_sdk
from flowboard.services.flow_client import flow_client
from flowboard.services import media as media_service

VIDEO_ASPECT = {
    "16:9": "VIDEO_ASPECT_RATIO_LANDSCAPE",
    "9:16": "VIDEO_ASPECT_RATIO_PORTRAIT",
    "1:1": "VIDEO_ASPECT_RATIO_SQUARE",
}

# Map wizard quality labels to SDK-accepted values.
_QUALITY_MAP = {
    "fast": "fast",
    "standard": "fast",   # wizard "Chuẩn" → SDK fast
    "high": "quality",    # wizard "Cao"   → SDK quality
    "lite": "lite",
    "quality": "quality",
}

_POLL_INTERVAL_S = 10.0
_POLL_MAX_CYCLES = 30


class ClipGenError(Exception):
    pass


def _to_video_aspect(aspect_ratio: str) -> str:
    return VIDEO_ASPECT.get(aspect_ratio, "VIDEO_ASPECT_RATIO_LANDSCAPE")


def _to_sdk_quality(quality: str) -> str:
    return _QUALITY_MAP.get(quality, "fast")


async def generate_clip(
    *,
    video_prompt: str,
    start_media_id: str,
    project_id: str,
    aspect_ratio: str,
    quality: str,
    paygate_tier: Optional[str] = None,
    sdk: Any = None,
    sleep: Optional[Callable[[float], Any]] = None,
    ingest: Optional[Callable[[list[dict]], None]] = None,
    interval_s: float = _POLL_INTERVAL_S,
    max_cycles: int = _POLL_MAX_CYCLES,
) -> str:
    sdk = sdk or get_flow_sdk()
    sleep = sleep or asyncio.sleep
    ingest = ingest or media_service.ingest_urls

    tier = paygate_tier or flow_client.paygate_tier
    if not tier:
        raise ClipGenError("paygate_tier_unknown")

    dispatch = await sdk.gen_video(
        prompt=video_prompt,
        project_id=project_id,
        start_media_id=start_media_id,
        aspect_ratio=_to_video_aspect(aspect_ratio),
        video_quality=_to_sdk_quality(quality),
        paygate_tier=tier,
    )
    if dispatch.get("error"):
        raise ClipGenError(str(dispatch["error"]))

    operation_names = dispatch.get("operation_names") or []
    if not operation_names:
        raise ClipGenError("no async operation returned")
    # workflows is set for low-priority / workflow-based models — pass it
    # through to check_async exactly as canvas processor.py does.
    workflows = dispatch.get("workflows") or None

    done_by_name: dict[str, bool] = {n: False for n in operation_names}
    entry_by_name: dict[str, dict] = {}
    op_errors: dict[str, str] = {}

    for _ in range(max_cycles):
        # Sleep first, then poll — mirrors canvas _handle_gen_video order.
        await sleep(interval_s)
        poll = await sdk.check_async(operation_names, workflows=workflows)
        if poll.get("error"):
            continue
        for op in poll.get("operations") or []:
            if not isinstance(op, dict):
                continue
            name = op.get("name")
            if not isinstance(name, str) or done_by_name.get(name, False):
                continue
            err = op.get("error")
            if isinstance(err, str) and err:
                done_by_name[name] = True
                op_errors[name] = err
                continue
            if op.get("done"):
                done_by_name[name] = True
                for e in op.get("media_entries") or []:
                    if isinstance(e, dict) and e.get("media_id"):
                        entry_by_name[name] = e
                        break
        if all(done_by_name.values()):
            break

    # Ingest succeeded entries (same as canvas — only URLs we actually have).
    succeeded = list(entry_by_name.values())
    with_urls = [e for e in succeeded if e.get("url")]
    if with_urls:
        try:
            ingest(with_urls)
        except Exception:  # noqa: BLE001
            pass

    if succeeded:
        return succeeded[0]["media_id"]

    first_err = next(iter(op_errors.values()), "timeout_waiting_video")
    raise ClipGenError(first_err)
