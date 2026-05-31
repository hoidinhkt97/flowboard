"""Resolve a wizard input (character / product / background) to a media_id.

Sources:
  - upload : client already uploaded via /api/upload; we pass media_id through.
  - gen    : client ran gen_image (4 variants) and chose one; pass-through too.
  - ai_gen : short description -> LLM expands to a full image prompt -> gen_image.

LLM + SDK are injected for testability (default to the real singletons).

Note on the LLM feature key: ``run_llm``'s first arg is a *feature*
(``"auto_prompt" | "vision" | "planner"``), not a provider name. Expanding a
short description into a detailed image prompt is the ``auto_prompt`` feature
(same one ``prompt_synth`` uses); the user's configured provider for that
feature handles the call.
"""
from __future__ import annotations

from typing import Any, Callable, Optional

from flowboard.services.flow_client import flow_client
from flowboard.services.flow_sdk import get_flow_sdk
from flowboard.services.llm import run_llm

_ASPECT = {
    "9:16": "IMAGE_ASPECT_RATIO_PORTRAIT",
    "16:9": "IMAGE_ASPECT_RATIO_LANDSCAPE",
    "1:1": "IMAGE_ASPECT_RATIO_SQUARE",
}

_AI_GEN_SYSTEM = (
    "Bạn là chuyên gia viết prompt tạo ảnh. Người dùng đưa mô tả ngắn về một "
    "nhân vật / sản phẩm / bối cảnh. Hãy trả về DUY NHẤT một prompt tiếng Anh "
    "mô tả ảnh chi tiết, rõ bố cục, ánh sáng, phong cách. Không giải thích."
)


class InputResolveError(Exception):
    pass


def to_image_aspect(aspect_ratio: str) -> str:
    return _ASPECT.get(aspect_ratio, "IMAGE_ASPECT_RATIO_LANDSCAPE")


async def resolve_ai_gen(
    *,
    description: str,
    project_id: str,
    aspect_ratio: str,
    variant_count: int = 4,
    paygate_tier: Optional[str] = None,
    llm_runner: Optional[Callable[..., Any]] = None,
    sdk: Any = None,
) -> dict:
    llm_runner = llm_runner or run_llm
    sdk = sdk or get_flow_sdk()
    full_prompt = (await llm_runner(
        "auto_prompt", description, system_prompt=_AI_GEN_SYSTEM, timeout=60.0
    )).strip()
    if not full_prompt:
        raise InputResolveError("LLM returned empty prompt")
    tier = paygate_tier or flow_client.paygate_tier
    if not tier:
        raise InputResolveError("paygate_tier_unknown")
    resp = await sdk.gen_image(
        prompt=full_prompt,
        project_id=project_id,
        aspect_ratio=to_image_aspect(aspect_ratio),
        ref_media_ids=None,
        variant_count=variant_count,
        paygate_tier=tier,
    )
    if resp.get("error"):
        raise InputResolveError(str(resp["error"]))
    return {
        "prompt": full_prompt,
        "media_ids": resp.get("media_ids") or [],
        "media_entries": resp.get("media_entries") or [],
    }
