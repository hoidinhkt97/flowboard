"""One scene's storyboard image: gen_image with refs [composite, background]."""
from __future__ import annotations

from typing import Any, Callable, Optional

from flowboard.services.flow_sdk import get_flow_sdk
from flowboard.services.flow_client import flow_client
from flowboard.services import media as media_service
from flowboard.services.video_pipeline.input_resolver import to_image_aspect


class StoryboardGenError(Exception):
    pass


async def generate_storyboard(
    *,
    image_prompt: str,
    composite_media_id: str,
    background_media_id: str,
    project_id: str,
    aspect_ratio: str,
    paygate_tier: Optional[str] = None,
    sdk: Any = None,
    ingest: Optional[Callable[[list[dict]], None]] = None,
) -> str:
    sdk = sdk or get_flow_sdk()
    ingest = ingest or media_service.ingest_urls
    tier = paygate_tier or flow_client.paygate_tier
    if not tier:
        raise StoryboardGenError("paygate_tier_unknown")
    resp = await sdk.gen_image(
        prompt=image_prompt,
        project_id=project_id,
        aspect_ratio=to_image_aspect(aspect_ratio),
        ref_media_ids=[composite_media_id, background_media_id],
        variant_count=1,
        paygate_tier=tier,
    )
    if resp.get("error"):
        raise StoryboardGenError(str(resp["error"]))
    entries = resp.get("media_entries") or []
    if not entries or not entries[0].get("media_id"):
        raise StoryboardGenError("no storyboard media returned")
    with_urls = [e for e in entries if e.get("url")]
    if with_urls:
        try:
            ingest(with_urls)
        except Exception:  # noqa: BLE001
            pass
    return entries[0]["media_id"]
