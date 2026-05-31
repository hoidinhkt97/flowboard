"""Render one video clip from a storyboard image via async i2v workflow."""
from __future__ import annotations

import asyncio
from typing import Any, Callable, Optional

from flowboard.services.flow_sdk import get_flow_sdk
from flowboard.services.flow_client import flow_client
from flowboard.services import media as media_service

VIDEO_ASPECT = {
    "16:9": "landscape",
    "9:16": "portrait",
    "1:1": "square",
}

_POLL_INTERVAL_S = 10.0
_POLL_MAX_CYCLES = 30


class ClipGenError(Exception):
    pass


def _to_video_aspect(aspect_ratio: str) -> str:
    return VIDEO_ASPECT.get(aspect_ratio, "landscape")


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
        video_quality=quality,
        paygate_tier=tier,
    )
    if dispatch.get("error"):
        raise ClipGenError(str(dispatch["error"]))

    operation_names = dispatch.get("operation_names") or []
    if not operation_names:
        raise ClipGenError("no async operation returned")

    for _ in range(max_cycles):
        poll = await sdk.check_async(operation_names=operation_names, workflows=None)
        if poll.get("error"):
            await sleep(interval_s)
            continue

        operations = poll.get("operations") or []
        done_seen = False
        for op in operations:
            if op.get("error"):
                raise ClipGenError(str(op["error"]))
            if not op.get("done"):
                continue

            done_seen = True
            entries = op.get("media_entries") or []
            if not entries or not entries[0].get("media_id"):
                raise ClipGenError("done with no media entries")

            with_urls = [e for e in entries if e.get("url")]
            if with_urls:
                try:
                    ingest(with_urls)
                except Exception:  # noqa: BLE001
                    pass
            return entries[0]["media_id"]

        if done_seen:
            raise ClipGenError("done with no media entries")

        await sleep(interval_s)

    raise ClipGenError("clip generation timeout")
