"""Pure transition rules for video-pipeline entities. No I/O, no DB —
trivially unit-testable. Orchestrator/handlers call these before writing
status so an out-of-order resume can't corrupt state."""
from __future__ import annotations

RUN_STATES = {"pending", "resolving", "generating", "merging", "done", "failed", "cancelled"}
VIDEO_STATES = {"pending", "composite_done", "scripted", "scenes_done", "merging", "done", "failed"}
SCENE_STATES = {"pending", "storyboard_running", "storyboard_done",
                "clip_running", "clip_done", "merged", "failed"}

_RUN_NEXT = {
    "pending": {"resolving", "failed", "cancelled"},
    "resolving": {"generating", "failed", "cancelled"},
    "generating": {"merging", "done", "failed", "cancelled"},
    "merging": {"done", "failed", "cancelled"},
    "done": set(),
    "failed": set(),
    "cancelled": set(),
}

_VIDEO_NEXT = {
    "pending": {"composite_done", "failed"},
    "composite_done": {"scripted", "failed"},
    "scripted": {"scenes_done", "failed"},
    "scenes_done": {"merging", "failed"},
    "merging": {"done", "failed"},
    "done": set(),
    "failed": set(),
}

_SCENE_NEXT = {
    "pending": {"storyboard_running", "failed"},
    "storyboard_running": {"storyboard_done", "failed"},
    "storyboard_done": {"clip_running", "failed"},
    "clip_running": {"clip_done", "failed"},
    "clip_done": {"merged", "failed"},
    "merged": set(),
    "failed": set(),
}


def _check(table, states, src, dst):
    if src not in states:
        raise ValueError(f"unknown source state: {src!r}")
    if dst not in states:
        raise ValueError(f"unknown target state: {dst!r}")
    return dst in table[src]


def can_transition_run(src: str, dst: str) -> bool:
    return _check(_RUN_NEXT, RUN_STATES, src, dst)


def can_transition_video(src: str, dst: str) -> bool:
    return _check(_VIDEO_NEXT, VIDEO_STATES, src, dst)


def can_transition_scene(src: str, dst: str) -> bool:
    return _check(_SCENE_NEXT, SCENE_STATES, src, dst)
