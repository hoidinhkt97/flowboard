"""Pipeline-type contract. Adding a new pipeline kind = add one module +
one registry line; the orchestrator and core UI do not change."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class Step:
    """One unit of work in a video's build sequence."""
    kind: str   # "composite" | "script" | "storyboard" | "clip" | "merge"
    label: str


@runtime_checkable
class PipelineType(Protocol):
    key: str
    label: str
    input_schema: dict

    def build_video_steps(self, ctx: dict) -> list[Step]:
        ...
