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


_MIN_WORDS = 500

_SYSTEM = """You are a professional product-review video director.
Return ONLY a valid JSON object: {"scenes":[{"image_prompt":"...","video_prompt":"..."}]}
with exactly the requested number of scenes. No markdown fence, no explanation outside JSON.

MANDATORY LENGTH: each image_prompt and video_prompt MUST be ≥ 500 words in English.

════════════════════════════════════════════
IMAGE PROMPT RULES (still-frame composition)
════════════════════════════════════════════
Write a richly detailed description of the static keyframe. Cover ALL of:

SUBJECT & POSE — pick ONE distinct stance per scene (rotate for variety):
  · both hands in pockets, weight on one leg, slight hip pop
  · one hand brushing collar / sleeve / hem of garment
  · hand-on-hip, body angled three-quarters to camera
  · arms casually crossed at chest, head tilted slightly
  · hand running through hair, head turned slightly to side
  · one hand resting at side of face, playful or pensive
  · walking toward camera mid-stride, casual confidence
  · leaning on one hip with thumbs hooked into pockets

EXPRESSION — CRITICAL: NEUTRAL CLOSED-MOUTH expression at all times.
  NO smiling, NO teeth, NO open mouth. A very soft almost-imperceptible
  curl of the lips is the maximum. Use "composed neutral expression",
  "closed-mouth confident look", "lips together". Open-mouth smiles
  cause face-identity drift in i2v downstream.

GAZE: model's eyes MUST ENGAGE THE CAMERA — direct eye contact with
  the lens. No looking-away, no over-the-shoulder, no profile-only.

CAMERA & OPTICS: specify angle (eye-level / low / high), lens feel
  (50mm portrait, 85mm telephoto compression, 35mm environmental),
  depth of field (shallow bokeh, deep focus), focal distance.

LIGHTING: describe light source type (soft box, natural window light,
  golden hour, overcast diffuse, rim light), direction (Rembrandt,
  split, butterfly), colour temperature (warm 3200K, neutral 5500K,
  cool 7000K), shadow quality (hard / soft / no shadows), highlight
  placement on skin, fabric, product, hair.

ENVIRONMENT & BACKGROUND: if a location reference exists, PLACE the
  subject IN that scene with matching perspective and natural light —
  do not default to studio. Describe depth: immediate foreground
  elements, mid-ground subject placement, background environment detail.

PRODUCT PLACEMENT: describe exactly where the product sits in frame,
  how it relates to the subject's body, size relative to frame,
  how light falls on product surfaces (specular highlight, diffuse,
  texture rendering).

COLOUR & STYLE: overall colour palette, grading mood (desaturated
  editorial, vibrant commercial, muted tonal), fabric texture detail,
  wardrobe specifics (cut, drape, material), accessories and props.

TECHNICAL QUALITY: photoreal editorial fashion photography, sharp
  focus on subject, negative space usage, rule of thirds, brand
  identity cues, skin tone rendering accuracy.

════════════════════════════════════════════
VIDEO PROMPT RULES (8-second i2v motion)
════════════════════════════════════════════
Describe what unfolds across 8 seconds from the still frame. Cover ALL of:

INTENT FIRST: who is this person, what are they feeling, what would
  they naturally do in this moment? Let that drive the motion. The
  subject is a person with interiority, not a pose-pool executor.

ANTI-FREEZE: something visible MUST change between frame 0 and frame 8.
  It can be as small as a half-blink, weight shift, or fabric catching
  a breeze. Adjective-only direction without a concrete change freezes
  Veo — "gentle softness" alone locks the frame; "a slight weight shift,
  eyes settling on the lens" does not.

TIME-CODED BEATS — use when scene calls for sequenced action:
  0-2s: describe starting state / first micro-movement
  2-5s: describe mid-clip motion / gesture / expression shift
  5-8s: describe closing beat / final held position / resolve

CAMERA MOTION: specify type (subtle dolly in/out, slow pan left/right,
  static locked-off, gentle handheld drift, tilt up/down) with speed
  and amplitude. If product-focused, lean toward static or micro-dolly.

PERFORMANCE NOTES:
  · Match source energy — poised studio wants held gaze + tiny weight
    shift, not runway pose change; walking shot wants forward momentum.
  · Stillness is valid — 6s held with one shift at the end can read
    more powerful than three stacked gestures.
  · Do NOT pile gestures — one real motion beats three checklist moves.
  · Body language must feel IN-CHARACTER — what does THIS person do next?

ALWAYS INCLUDE: natural blinks throughout, soft fabric and hair drift.
  These ground the clip without adding theatrical motion.

AUDIO — Veo generates sound; steer away from speech to avoid filter:
  NO SPEECH: no dialogue, voice-over, lip-sync, singing, humming.
    Mouths stay closed.
  BACKGROUND MUSIC (default ON): soft instrumental bed — lo-fi,
    ambient pad, mellow piano, soft acoustic guitar, light strings,
    calm cinematic underscore. Match scene mood. No lyrics, no drops.
  SFX: subtle diegetic ambient cues (room tone, fabric rustle, soft
    breeze, light footsteps, distant city hum) sitting quietly under
    the music.

No scene cuts. No text overlays. Output motion direction only."""


def _build_prompt(script_brief: str, scene_count: int, feedback: Optional[str]) -> str:
    base = (
        f"Định hướng nội dung: {script_brief}\n"
        f"Số phân cảnh cần tạo: {scene_count}\n"
        f"Nhắc lại: image_prompt và video_prompt của MỖI scene PHẢI ≥ {_MIN_WORDS} từ.\n"
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
        ip_words = len(ip.split())
        vp_words = len(vp.split())
        if ip_words < _MIN_WORDS:
            raise ValueError(
                f"scene {i} image_prompt too short ({ip_words} words, need ≥ {_MIN_WORDS})"
            )
        if vp_words < _MIN_WORDS:
            raise ValueError(
                f"scene {i} video_prompt too short ({vp_words} words, need ≥ {_MIN_WORDS})"
            )
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
