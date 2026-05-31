"""Generate composite (character + product) base images for a product.

gen_image with ref_media_ids=[character, product], variant_count=n.
One composite per video. Results are ingested into the media cache so the
frontend can serve them via /media/{id}.
"""
from __future__ import annotations

from typing import Any, Callable, Optional

from flowboard.services.flow_sdk import get_flow_sdk
from flowboard.services.flow_client import flow_client
from flowboard.services import media as media_service
from flowboard.services.video_pipeline.input_resolver import to_image_aspect


class CompositeGenError(Exception):
    pass


_PROMPT_TMPL = (
    "Compose a single photorealistic image placing the character together "
    "with the product naturally in one frame, suitable as the opening shot "
    "of a product-review video. Keep the character's identity and the "
    "product's appearance faithful to the reference images. Context: {brief}"
)


async def generate_composites(
    *,
    character_media_id: str,
    product_media_id: str,
    project_id: str,
    aspect_ratio: str,
    variant_count: int,
    script_brief: str,
    paygate_tier: Optional[str] = None,
    sdk: Any = None,
    ingest: Optional[Callable[[list[dict]], None]] = None,
) -> list[dict]:
    sdk = sdk or get_flow_sdk()
    ingest = ingest or media_service.ingest_urls
    tier = paygate_tier or flow_client.paygate_tier
    if not tier:
        raise CompositeGenError("paygate_tier_unknown")

    resp = await sdk.gen_image(
        prompt=_PROMPT_TMPL.format(brief=script_brief or "n/a"),
        project_id=project_id,
        aspect_ratio=to_image_aspect(aspect_ratio),
        ref_media_ids=[character_media_id, product_media_id],
        variant_count=variant_count,
        paygate_tier=tier,
    )
    if resp.get("error"):
        raise CompositeGenError(str(resp["error"]))
    entries = resp.get("media_entries") or []
    if len(entries) < variant_count:
        raise CompositeGenError(
            f"requested {variant_count} composites, got {len(entries)}")
    with_urls = [e for e in entries if e.get("url")]
    if with_urls:
        try:
            ingest(with_urls)
        except Exception:  # noqa: BLE001 — caching is best-effort
            pass
    return entries[:variant_count]
