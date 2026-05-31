"""Generate one video's script: M scenes, each with image_prompt +
video_prompt. LLM output is JSON-validated with re-prompt-on-failure retry.
LLM runner injected for testability."""
from __future__ import annotations

import json
import re
from typing import Any, Callable, Optional

from flowboard.services.llm import run_llm


class ScriptPlanError(Exception):
    pass


_SYSTEM = (
    "Bạn là đạo diễn video review sản phẩm. Trả về DUY NHẤT một JSON object "
    'dạng {"scenes":[{"image_prompt": "...", "video_prompt": "..."}]} với đúng '
    "số phân cảnh được yêu cầu. image_prompt mô tả bố cục khung hình tĩnh "
    "(tiếng Anh). video_prompt mô tả chuyển động/hành động cho i2v, ngắn gọn "
    "(≤ 25 từ, tiếng Anh). Không thêm giải thích, không markdown."
)


def _build_prompt(script_brief: str, scene_count: int, feedback: Optional[str]) -> str:
    base = (
        f"Định hướng nội dung: {script_brief}\n"
        f"Số phân cảnh cần tạo: {scene_count}\n"
        f'Trả về JSON: {{"scenes": [ ... {scene_count} phần tử ... ]}}'
    )
    if feedback:
        base += f"\n\nLần trước lỗi: {feedback}. Hãy sửa và trả lại JSON hợp lệ."
    return base


def _extract_json(text: str) -> Any:
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    return json.loads(text)


def _validate(parsed: Any, scene_count: int) -> list[dict]:
    if not isinstance(parsed, dict) or "scenes" not in parsed:
        raise ValueError("missing 'scenes' key")
    scenes = parsed["scenes"]
    if not isinstance(scenes, list) or len(scenes) != scene_count:
        raise ValueError(f"expected {scene_count} scenes, got {len(scenes) if isinstance(scenes, list) else 'non-list'}")
    out = []
    for i, sc in enumerate(scenes):
        if not isinstance(sc, dict):
            raise ValueError(f"scene {i} not an object")
        ip = (sc.get("image_prompt") or "").strip()
        vp = (sc.get("video_prompt") or "").strip()
        if not ip or not vp:
            raise ValueError(f"scene {i} missing image_prompt/video_prompt")
        out.append({"image_prompt": ip, "video_prompt": vp})
    return out


async def plan_script(
    *,
    script_brief: str,
    scene_count: int,
    llm_runner: Optional[Callable[..., Any]] = None,
    max_retries: int = 2,
) -> list[dict]:
    llm_runner = llm_runner or run_llm
    feedback: Optional[str] = None
    last_err = "unknown"
    for _ in range(max_retries):
        raw = await llm_runner("planner", _build_prompt(script_brief, scene_count, feedback),
                               system_prompt=_SYSTEM, timeout=90.0)
        try:
            parsed = _extract_json(raw)
            return _validate(parsed, scene_count)
        except (json.JSONDecodeError, ValueError) as e:
            last_err = str(e)
            feedback = last_err
    raise ScriptPlanError(f"failed to produce valid script after {max_retries} attempts: {last_err}")
