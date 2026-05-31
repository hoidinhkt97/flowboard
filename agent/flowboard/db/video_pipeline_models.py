"""SQLModel tables for the Video Pipeline feature.

Prefixed ``VideoPipeline*`` to avoid colliding with the canvas planner's
existing ``PipelineRun`` (db/models.py), which is unrelated.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import UniqueConstraint
from sqlmodel import Field, SQLModel, Column, JSON

from .models import _utcnow


class VideoPipelineTemplate(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    type_key: str = "product_review"
    params: dict = Field(default_factory=dict, sa_column=Column(JSON))
    is_builtin: bool = False
    position: int = 0
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


class VideoPipelineRun(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    short_id: str = Field(index=True, unique=True)
    type_key: str = "product_review"
    flow_project_id: Optional[str] = None
    inputs: dict = Field(default_factory=dict, sa_column=Column(JSON))
    status: str = "pending"  # pending|resolving|generating|merging|done|failed|cancelled
    error: Optional[str] = None
    cancelled: bool = False
    created_at: datetime = Field(default_factory=_utcnow)
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None


class VideoPipelineProduct(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    run_id: int = Field(foreign_key="videopipelinerun.id", index=True)
    product_index: int
    source: str = "upload"  # upload|gen|ai_gen
    media_id: Optional[str] = None
    prompt: Optional[str] = None
    __table_args__ = (
        UniqueConstraint("run_id", "product_index", name="uq_run_product"),
    )


class VideoPipelineVideo(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    run_id: int = Field(foreign_key="videopipelinerun.id", index=True)
    product_index: int
    video_index: int
    composite_media_id: Optional[str] = None
    merged_local_path: Optional[str] = None
    merged_url: Optional[str] = None
    status: str = "pending"  # pending|composite_done|scripted|scenes_done|merging|done|failed
    error: Optional[str] = None
    duration_sec: Optional[float] = None
    file_size_bytes: Optional[int] = None
    composite_attempts: int = 0
    updated_at: datetime = Field(default_factory=_utcnow)
    __table_args__ = (
        UniqueConstraint("run_id", "product_index", "video_index",
                         name="uq_run_product_video"),
    )


class VideoPipelineScene(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    run_id: int = Field(foreign_key="videopipelinerun.id", index=True)
    product_index: int
    video_index: int
    scene_index: int
    image_prompt: str = ""
    video_prompt: str = ""
    storyboard_media_id: Optional[str] = None
    clip_media_id: Optional[str] = None
    status: str = "pending"  # pending|storyboard_running|storyboard_done|clip_running|clip_done|merged|failed
    error: Optional[str] = None
    storyboard_attempts: int = 0
    clip_attempts: int = 0
    updated_at: datetime = Field(default_factory=_utcnow)
    __table_args__ = (
        UniqueConstraint("run_id", "product_index", "video_index", "scene_index",
                         name="uq_run_product_video_scene"),
    )
