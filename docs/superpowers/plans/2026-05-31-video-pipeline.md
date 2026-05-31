# Video Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the **Video Pipeline** feature — a single-page wizard that takes a character + multiple products + background + script brief + parameters, then automatically (per product) generates scripts, composites character+product images, builds per-scene storyboards, renders per-scene clips via Flow i2v, and merges clips into finished `.mp4` files downloadable by the user.

**Architecture:** A backend `services/video_pipeline/` module driven by an extensible **pipeline-type registry** (v1 ships exactly one type: `product_review`). An idempotent, resume-safe orchestrator runs as an `asyncio` background task. Five new `VideoPipeline*` SQLModel tables track run → product → video → scene state. The frontend adds `react-router-dom` routing (canvas stays at `/`), a wizard page, a runs list, and a progress page. **Realtime updates use polling** (reuse the existing `src/store/pipeline.ts` pattern) — every transition is written to DB + `manifest.json`, and the progress page polls `GET /runs/{sid}`. No WebSocket client is introduced in v1.

**Tech Stack:**
- **Backend:** FastAPI + SQLModel (existing), `asyncio` orchestration, `imageio-ffmpeg` portable binary via subprocess for merging.
- **Backend reuse:** `flow_sdk` (create_project / gen_image / gen_video / check_async), `services/llm` (`run_llm`), `services/vision` (`describe_media`), `services/media` (cache + `ingest_urls`), `routes/upload`, `routes/media`.
- **Frontend:** React 18 + Vite 5 (existing), Zustand (existing), `react-router-dom` v6 (new).
- **Testing:** pytest + `hypothesis` (backend, existing infra); vitest + `@testing-library/react` + `msw` (frontend, **net-new** — set up in Phase 7).

**Reference spec:** [docs/superpowers/specs/2026-05-31-video-pipeline-design.md](../specs/2026-05-31-video-pipeline-design.md)

**Branch:** `feature/pipline-video-creator` (already checked out)

**Key decisions for this plan (confirmed with user):**
1. **Realtime transport = polling** (not WebSocket). Backend records every transition to DB + manifest; frontend polls `GET /api/video-pipeline/runs/{sid}`.
2. **One full plan, all 7 phases** (this document).

**Conventions grounded in the existing codebase:**
- Backend package root: `agent/flowboard/`. Tests live in `agent/tests/` and run via `pytest` from `agent/`.
- `conftest.py` sets `FLOWBOARD_STORAGE` to a tmp dir, `FLOWBOARD_DB` to a tmp sqlite, `FLOWBOARD_PLANNER_BACKEND=mock`. An autouse `_fresh_db` fixture drops + recreates all tables before each test. A `client` fixture returns `TestClient(app)`.
- Models: `db/models.py` defines `_utcnow()` and imports `from sqlalchemy import UniqueConstraint`, `from sqlmodel import Field, SQLModel, Column, JSON`.
- Sessions: `db/session.py` exposes `engine`, `init_db()` (calls `SQLModel.metadata.create_all(engine)`), and a `get_session()` context manager.
- Config: `config.py` exposes `STORAGE_DIR` and `ROOT`.
- Flow SDK singleton: `get_flow_sdk()`.
- Routers follow `router = APIRouter(prefix="/api", tags=[...])` and are registered in `main.py` via `app.include_router(...)`.
- Background tasks follow the `routes/plans.py` pattern: `asyncio.create_task(..., name=...)` stored in a module dict with an `add_done_callback` cleanup.

**Backend signatures this plan depends on (verified):**
- `await get_flow_sdk().create_project(title: str, tool="PINHOLE") -> {"raw":..., "project_id": str}` (or `{"raw":..., "error": str}`).
- `await get_flow_sdk().gen_image(prompt, project_id, aspect_ratio="IMAGE_ASPECT_RATIO_LANDSCAPE", ref_media_ids: list[str]|None, variant_count: int, paygate_tier=None) -> {"raw":..., "media_ids": list[str], "media_entries": [{"media_id","url","mediaType"}]}` (or `{"error":...}`).
- `await get_flow_sdk().gen_video(prompt, project_id, start_media_id: str|None, aspect_ratio="VIDEO_ASPECT_RATIO_LANDSCAPE", video_quality=None, paygate_tier=...) -> {"raw":..., "operation_names": list[str], "workflows"?: list}` (or `{"error":...}`). **Async**: caller polls `await sdk.check_async(operation_names, workflows=workflows) -> {"operations": [{"name","done","error?","media_entries":[{"media_id","url"}]}]}` until all `done`. Reuse interval/cycles from `worker/processor.py` (`VIDEO_POLL_INTERVAL_S=10.0`, `VIDEO_POLL_MAX_CYCLES=30`).
- `await run_llm(provider_name: str, user_prompt: str, *, system_prompt=None, attachments: list[str]|None=None, timeout: float=90.0) -> str` (from `services/llm`).
- `await describe_media(media_id: str, *, node_id=None) -> str` (from `services/vision`).
- `media_service.ingest_urls(entries: list[dict])` persists `{media_id,url}` entries so `/media/{id}` can serve bytes. `media_service.cached_path(media_id) -> Path|None`.

**Frontend facts this plan depends on (verified):**
- App mounts `<App/>` in `src/main.tsx`. `App.tsx` renders `ProjectSidebar | canvas-wrap`. **No router yet.** `react-router-dom` is **not** installed.
- API client: `api<T>(path, init?)` in `src/api/client.ts`; endpoint functions return typed DTOs. Vite proxies `/api`, `/media`, `/ws` → `localhost:8101`.
- Upload: `uploadImage(file, projectId, nodeId?) -> {media_id, mime, size, width, height, aspect_ratio}` in `src/api/client.ts`. Project id via `useGenerationStore.getState().ensureProjectId()`.
- Stores in `src/store/*.ts` use `create<State>((set,get)=>({...}))`. `src/store/pipeline.ts` shows the recursive `setTimeout` polling pattern (1500ms).
- Styling: CSS custom properties in `src/styles.css`, BEM naming (`.block__el--mod`). Dark theme tokens (`--bg`, `--panel`, `--accent`, etc.).
- **No frontend test infra installed** (`tests/e2e/` dirs are empty; no vitest/testing-library/msw in `package.json`). Phase 7 sets this up.
- `src/components/pipeline/` does **not** exist; `InputCard` is net-new.

---

## Phase 1 — Schema + Template CRUD + Routing skeleton

**Outcome:** New DB tables exist and migrate cleanly; `GET /api/video-pipeline/types` and template CRUD work end-to-end; the frontend has routing with the canvas preserved at `/` and a "Video Pipeline" sidebar entry navigating to placeholder pages. Mergeable on its own.

### Task 1.1: Add `VideoPipeline*` SQLModel tables

**Files:**
- Create: `agent/flowboard/db/video_pipeline_models.py`
- Modify: `agent/flowboard/db/session.py` (ensure new models are imported before `create_all`)
- Create: `agent/tests/test_video_pipeline_models.py`

- [ ] **Step 1: Write the failing test**

Write to `agent/tests/test_video_pipeline_models.py`:

```python
from datetime import datetime

from sqlmodel import select

from flowboard.db.session import get_session
from flowboard.db.video_pipeline_models import (
    VideoPipelineTemplate,
    VideoPipelineRun,
    VideoPipelineProduct,
    VideoPipelineVideo,
    VideoPipelineScene,
)


def test_run_roundtrip_with_json_inputs():
    with get_session() as s:
        run = VideoPipelineRun(
            short_id="vpr_test1",
            type_key="product_review",
            inputs={"aspect_ratio": "9:16", "video_count": 2, "scene_count": 3},
        )
        s.add(run)
        s.commit()
        s.refresh(run)
        assert run.id is not None
        assert run.status == "pending"
        assert isinstance(run.created_at, datetime)

    with get_session() as s:
        loaded = s.exec(
            select(VideoPipelineRun).where(VideoPipelineRun.short_id == "vpr_test1")
        ).one()
        assert loaded.inputs["aspect_ratio"] == "9:16"
        assert loaded.inputs["video_count"] == 2


def test_unique_constraints_enforced():
    import pytest
    from sqlalchemy.exc import IntegrityError

    with get_session() as s:
        s.add(VideoPipelineRun(short_id="vpr_dup"))
        s.commit()
    with get_session() as s:
        s.add(VideoPipelineRun(short_id="vpr_dup"))
        with pytest.raises(IntegrityError):
            s.commit()


def test_child_rows_and_composite_uniqueness():
    import pytest
    from sqlalchemy.exc import IntegrityError

    with get_session() as s:
        run = VideoPipelineRun(short_id="vpr_kids")
        s.add(run)
        s.commit()
        s.refresh(run)
        rid = run.id

    with get_session() as s:
        s.add(VideoPipelineVideo(run_id=rid, product_index=0, video_index=0))
        s.commit()
    with get_session() as s:
        s.add(VideoPipelineVideo(run_id=rid, product_index=0, video_index=0))
        with pytest.raises(IntegrityError):
            s.commit()


def test_template_builtin_flag_defaults():
    with get_session() as s:
        t = VideoPipelineTemplate(name="Default", type_key="product_review",
                                  params={"scene_count": 3})
        s.add(t)
        s.commit()
        s.refresh(t)
        assert t.is_builtin is False
        assert t.position == 0
        assert t.params["scene_count"] == 3
```

Run: `cd agent && python -m pytest tests/test_video_pipeline_models.py -q`. Expect ImportError (module doesn't exist).

- [ ] **Step 2: Implement the models**

Write to `agent/flowboard/db/video_pipeline_models.py`:

```python
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
```

- [ ] **Step 3: Ensure tables are created**

In `agent/flowboard/db/session.py`, find where models are imported for metadata registration (the existing `from . import models` or equivalent before `create_all`). Add an import so the new tables register. If `init_db()` imports `models` explicitly, add alongside it:

```python
from . import models  # noqa: F401  (existing)
from . import video_pipeline_models  # noqa: F401  (new — registers VideoPipeline* tables)
```

If `session.py` does not import models directly (relies on import side-effects elsewhere), instead add the import at the top of `agent/flowboard/main.py` near the other db imports. Verify by checking which file triggers `create_all`.

Run: `cd agent && python -m pytest tests/test_video_pipeline_models.py -q`. Expect all 4 tests pass.

- [ ] **Step 4: Commit**

```bash
git add agent/flowboard/db/video_pipeline_models.py agent/flowboard/db/session.py agent/tests/test_video_pipeline_models.py
git commit -m "feat(video-pipeline): add VideoPipeline* SQLModel tables"
```

---

### Task 1.2: Pure state-machine module (transition rules)

**Files:**
- Create: `agent/flowboard/services/video_pipeline/__init__.py` (empty)
- Create: `agent/flowboard/services/video_pipeline/state_machine.py`
- Create: `agent/tests/test_video_pipeline_state_machine.py`

- [ ] **Step 1: Write the failing test** (property-based with hypothesis, plus explicit cases)

Write to `agent/tests/test_video_pipeline_state_machine.py`:

```python
import pytest
from hypothesis import given, strategies as st

from flowboard.services.video_pipeline import state_machine as sm


def test_scene_forward_transitions_allowed():
    assert sm.can_transition_scene("pending", "storyboard_running")
    assert sm.can_transition_scene("storyboard_running", "storyboard_done")
    assert sm.can_transition_scene("storyboard_done", "clip_running")
    assert sm.can_transition_scene("clip_running", "clip_done")
    assert sm.can_transition_scene("clip_done", "merged")


def test_scene_backward_transition_rejected():
    assert not sm.can_transition_scene("clip_done", "pending")
    assert not sm.can_transition_scene("merged", "storyboard_running")


def test_scene_failure_allowed_from_any_running():
    assert sm.can_transition_scene("storyboard_running", "failed")
    assert sm.can_transition_scene("clip_running", "failed")


def test_video_transitions():
    assert sm.can_transition_video("pending", "composite_done")
    assert sm.can_transition_video("composite_done", "scripted")
    assert sm.can_transition_video("scripted", "scenes_done")
    assert sm.can_transition_video("scenes_done", "merging")
    assert sm.can_transition_video("merging", "done")
    assert not sm.can_transition_video("done", "pending")


def test_run_terminal_states_are_sinks():
    for terminal in ("done", "failed", "cancelled"):
        for nxt in sm.RUN_STATES:
            if nxt != terminal:
                assert not sm.can_transition_run(terminal, nxt)


@given(st.sampled_from(sorted(sm.SCENE_STATES)),
       st.sampled_from(sorted(sm.SCENE_STATES)))
def test_scene_transition_never_raises(a, b):
    # Pure predicate: must return a bool for any state pair, never raise.
    assert isinstance(sm.can_transition_scene(a, b), bool)


def test_unknown_state_raises_valueerror():
    with pytest.raises(ValueError):
        sm.can_transition_scene("bogus", "merged")
```

Run: `cd agent && python -m pytest tests/test_video_pipeline_state_machine.py -q`. Expect ImportError.

- [ ] **Step 2: Implement the state machine**

Create empty `agent/flowboard/services/video_pipeline/__init__.py`.

Write to `agent/flowboard/services/video_pipeline/state_machine.py`:

```python
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
```

Run: `cd agent && python -m pytest tests/test_video_pipeline_state_machine.py -q`. Expect pass. If `hypothesis` is not installed, add it to `agent/requirements.txt` (or the dev extras) and `pip install hypothesis`, then re-run.

- [ ] **Step 3: Commit**

```bash
git add agent/flowboard/services/video_pipeline/__init__.py agent/flowboard/services/video_pipeline/state_machine.py agent/tests/test_video_pipeline_state_machine.py
git commit -m "feat(video-pipeline): pure state-machine transition rules"
```

---

### Task 1.3: Storage path helpers + manifest roundtrip

**Files:**
- Create: `agent/flowboard/services/video_pipeline/storage.py`
- Create: `agent/tests/test_video_pipeline_storage.py`

- [ ] **Step 1: Write the failing test**

Write to `agent/tests/test_video_pipeline_storage.py`:

```python
from pathlib import Path

from flowboard.services.video_pipeline import storage


def test_run_dir_under_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "STORAGE_DIR", tmp_path)
    d = storage.run_dir("vpr_abc")
    assert d == tmp_path / "video_pipeline" / "vpr_abc"


def test_composite_path_naming(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "STORAGE_DIR", tmp_path)
    p = storage.composite_path("vpr_abc", product_index=1, video_index=2)
    assert p.name == "p1-v2.png"
    assert "composites" in p.parts


def test_storyboard_and_clip_and_merged_paths(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "STORAGE_DIR", tmp_path)
    sb = storage.storyboard_path("vpr_abc", 0, 1, 2)
    assert sb.name == "p0-v1-s2.png" and "storyboards" in sb.parts
    clip = storage.clip_path("vpr_abc", 0, 1, 2)
    assert clip.name == "p0-v1-s2.mp4" and "clips" in clip.parts
    merged = storage.merged_path("vpr_abc", 0, 1)
    assert merged.name == "p0-v1.mp4" and "merged" in merged.parts


def test_ensure_run_dirs_creates_tree(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "STORAGE_DIR", tmp_path)
    storage.ensure_run_dirs("vpr_abc")
    base = tmp_path / "video_pipeline" / "vpr_abc"
    for sub in ("composites", "storyboards", "clips", "merged"):
        assert (base / sub).is_dir()


def test_manifest_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "STORAGE_DIR", tmp_path)
    storage.ensure_run_dirs("vpr_abc")
    payload = {"run": {"short_id": "vpr_abc", "status": "generating"}, "videos": []}
    storage.write_manifest("vpr_abc", payload)
    loaded = storage.read_manifest("vpr_abc")
    assert loaded == payload


def test_read_manifest_missing_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "STORAGE_DIR", tmp_path)
    assert storage.read_manifest("nope") is None
```

Run: `cd agent && python -m pytest tests/test_video_pipeline_storage.py -q`. Expect ImportError.

- [ ] **Step 2: Implement storage helpers**

Write to `agent/flowboard/services/video_pipeline/storage.py`:

```python
"""Filesystem layout + manifest roundtrip for video-pipeline runs.

storage/video_pipeline/<short_id>/{composites,storyboards,clips,merged}/...
plus manifest.json (resume snapshot). Input ref media stays in the media
cache (services/media), not copied here.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Optional

from flowboard.config import STORAGE_DIR

_BASE = "video_pipeline"
_SUBDIRS = ("composites", "storyboards", "clips", "merged")


def run_dir(short_id: str) -> Path:
    return STORAGE_DIR / _BASE / short_id


def ensure_run_dirs(short_id: str) -> Path:
    base = run_dir(short_id)
    for sub in _SUBDIRS:
        (base / sub).mkdir(parents=True, exist_ok=True)
    return base


def composite_path(short_id: str, product_index: int, video_index: int) -> Path:
    return run_dir(short_id) / "composites" / f"p{product_index}-v{video_index}.png"


def storyboard_path(short_id: str, product_index: int, video_index: int, scene_index: int) -> Path:
    return run_dir(short_id) / "storyboards" / f"p{product_index}-v{video_index}-s{scene_index}.png"


def clip_path(short_id: str, product_index: int, video_index: int, scene_index: int) -> Path:
    return run_dir(short_id) / "clips" / f"p{product_index}-v{video_index}-s{scene_index}.mp4"


def merged_path(short_id: str, product_index: int, video_index: int) -> Path:
    return run_dir(short_id) / "merged" / f"p{product_index}-v{video_index}.mp4"


def manifest_path(short_id: str) -> Path:
    return run_dir(short_id) / "manifest.json"


def write_manifest(short_id: str, payload: dict[str, Any]) -> None:
    ensure_run_dirs(short_id)
    target = manifest_path(short_id)
    # atomic write: tmp in same dir then os.replace
    fd, tmp = tempfile.mkstemp(dir=str(target.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2, default=str)
        os.replace(tmp, target)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def read_manifest(short_id: str) -> Optional[dict[str, Any]]:
    p = manifest_path(short_id)
    if not p.exists():
        return None
    with p.open(encoding="utf-8") as f:
        return json.load(f)
```

Run: `cd agent && python -m pytest tests/test_video_pipeline_storage.py -q`. Expect pass.

> Note: tests monkeypatch `storage.STORAGE_DIR`. Because the helpers reference the module-level name `STORAGE_DIR`, the patch takes effect. Do not alias the import — keep the bare name.

- [ ] **Step 3: Commit**

```bash
git add agent/flowboard/services/video_pipeline/storage.py agent/tests/test_video_pipeline_storage.py
git commit -m "feat(video-pipeline): storage path helpers + atomic manifest roundtrip"
```

---

### Task 1.4: Short-id generator

**Files:**
- Create: `agent/flowboard/services/video_pipeline/ids.py`
- Create: `agent/tests/test_video_pipeline_ids.py`

- [ ] **Step 1: Write the failing test**

Write to `agent/tests/test_video_pipeline_ids.py`:

```python
import re

from flowboard.services.video_pipeline.ids import new_short_id


def test_short_id_format():
    sid = new_short_id()
    assert re.fullmatch(r"vpr_[0-9a-z]{5}", sid), sid


def test_short_id_unique_enough():
    seen = {new_short_id() for _ in range(2000)}
    assert len(seen) > 1990  # collisions vanishingly rare
```

- [ ] **Step 2: Implement**

Write to `agent/flowboard/services/video_pipeline/ids.py`:

```python
"""Human-friendly short ids for runs: ``vpr_<5 base32 chars>``."""
from __future__ import annotations

import secrets

_ALPHABET = "0123456789abcdefghijklmnopqrstuvwxyz"


def new_short_id() -> str:
    body = "".join(secrets.choice(_ALPHABET) for _ in range(5))
    return f"vpr_{body}"
```

Run: `cd agent && python -m pytest tests/test_video_pipeline_ids.py -q`. Expect pass.

- [ ] **Step 3: Commit**

```bash
git add agent/flowboard/services/video_pipeline/ids.py agent/tests/test_video_pipeline_ids.py
git commit -m "feat(video-pipeline): short-id generator"
```

---

### Task 1.5: Pipeline-type registry + `product_review` skeleton

**Files:**
- Create: `agent/flowboard/services/video_pipeline/types/__init__.py` (empty)
- Create: `agent/flowboard/services/video_pipeline/types/base.py`
- Create: `agent/flowboard/services/video_pipeline/types/product_review.py`
- Create: `agent/flowboard/services/video_pipeline/types/registry.py`
- Create: `agent/tests/test_video_pipeline_registry.py`

- [ ] **Step 1: Write the failing test**

Write to `agent/tests/test_video_pipeline_registry.py`:

```python
from flowboard.services.video_pipeline.types import registry


def test_product_review_registered():
    t = registry.get("product_review")
    assert t.key == "product_review"
    assert t.label
    assert "character" in t.input_schema
    assert "products" in t.input_schema
    assert "background" in t.input_schema


def test_list_types_returns_serializable():
    items = registry.list_types()
    assert any(i["key"] == "product_review" for i in items)
    for i in items:
        assert set(i.keys()) >= {"key", "label", "input_schema"}


def test_unknown_type_raises():
    import pytest
    with pytest.raises(KeyError):
        registry.get("does_not_exist")


def test_build_video_steps_scene_count():
    t = registry.get("product_review")
    steps = t.build_video_steps({"scene_count": 2})
    kinds = [s.kind for s in steps]
    assert kinds[0] == "composite"
    assert kinds[1] == "script"
    assert kinds.count("storyboard") == 2
    assert kinds.count("clip") == 2
    assert kinds[-1] == "merge"
```

- [ ] **Step 2: Implement base protocol + product_review + registry**

Create empty `agent/flowboard/services/video_pipeline/types/__init__.py`.

Write to `agent/flowboard/services/video_pipeline/types/base.py`:

```python
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
```

Write to `agent/flowboard/services/video_pipeline/types/product_review.py`:

```python
from __future__ import annotations

from .base import Step


class ProductReviewType:
    key = "product_review"
    label = "Product Review"
    input_schema = {
        "character": {"required": True, "kind": "media", "label": "Nhân vật"},
        "products": {"required": True, "kind": "media_list", "min": 1, "label": "Sản phẩm"},
        "background": {"required": True, "kind": "media", "label": "Bối cảnh"},
        "script_brief": {"required": True, "kind": "text", "label": "Prompt kịch bản"},
    }

    def build_video_steps(self, ctx: dict) -> list[Step]:
        scene_count = int(ctx.get("scene_count", 3))
        steps: list[Step] = [
            Step("composite", "Ghép nhân vật + sản phẩm"),
            Step("script", "Sinh kịch bản"),
        ]
        for j in range(scene_count):
            steps.append(Step("storyboard", f"Storyboard scene {j}"))
            steps.append(Step("clip", f"Clip scene {j}"))
        steps.append(Step("merge", "Ghép video"))
        return steps
```

Write to `agent/flowboard/services/video_pipeline/types/registry.py`:

```python
from __future__ import annotations

from .base import PipelineType
from .product_review import ProductReviewType

REGISTRY: dict[str, PipelineType] = {
    ProductReviewType.key: ProductReviewType(),
}


def get(key: str) -> PipelineType:
    if key not in REGISTRY:
        raise KeyError(key)
    return REGISTRY[key]


def list_types() -> list[dict]:
    return [
        {"key": t.key, "label": t.label, "input_schema": t.input_schema}
        for t in REGISTRY.values()
    ]
```

Run: `cd agent && python -m pytest tests/test_video_pipeline_registry.py -q`. Expect pass.

- [ ] **Step 3: Commit**

```bash
git add agent/flowboard/services/video_pipeline/types/ agent/tests/test_video_pipeline_registry.py
git commit -m "feat(video-pipeline): pipeline-type registry + product_review skeleton"
```

---

### Task 1.6: Template CRUD service + builtin seeding

**Files:**
- Create: `agent/flowboard/services/video_pipeline/templates.py`
- Create: `agent/tests/test_video_pipeline_templates.py`

- [ ] **Step 1: Write the failing test**

Write to `agent/tests/test_video_pipeline_templates.py`:

```python
import pytest

from flowboard.services.video_pipeline import templates


def test_create_and_list():
    t = templates.create_template(name="My", type_key="product_review",
                                  params={"scene_count": 4})
    assert t.id is not None
    rows = templates.list_templates()
    assert any(r.id == t.id for r in rows)


def test_update_template():
    t = templates.create_template(name="A", type_key="product_review", params={})
    updated = templates.update_template(t.id, name="B", params={"quality": "high"})
    assert updated.name == "B"
    assert updated.params["quality"] == "high"


def test_delete_template():
    t = templates.create_template(name="X", type_key="product_review", params={})
    templates.delete_template(t.id)
    assert all(r.id != t.id for r in templates.list_templates())


def test_builtin_cannot_be_modified_or_deleted():
    t = templates.create_template(name="Builtin", type_key="product_review",
                                  params={}, is_builtin=True)
    with pytest.raises(templates.TemplateProtectedError):
        templates.update_template(t.id, name="nope")
    with pytest.raises(templates.TemplateProtectedError):
        templates.delete_template(t.id)


def test_seed_builtins_idempotent():
    templates.seed_builtins()
    first = [r for r in templates.list_templates() if r.is_builtin]
    templates.seed_builtins()
    second = [r for r in templates.list_templates() if r.is_builtin]
    assert len(first) == len(second)
    assert len(first) >= 1


def test_update_missing_raises():
    with pytest.raises(templates.TemplateNotFoundError):
        templates.update_template(999999, name="ghost")
```

- [ ] **Step 2: Implement template service**

Write to `agent/flowboard/services/video_pipeline/templates.py`:

```python
from __future__ import annotations

from typing import Optional

from sqlmodel import select

from flowboard.db.session import get_session
from flowboard.db.models import _utcnow
from flowboard.db.video_pipeline_models import VideoPipelineTemplate


class TemplateNotFoundError(Exception):
    pass


class TemplateProtectedError(Exception):
    pass


_BUILTINS = [
    {"name": "Review nhanh 9:16", "type_key": "product_review",
     "params": {"aspect_ratio": "9:16", "scene_count": 3, "quality": "fast",
                "crossfade_sec": 0.0, "audio_enabled": True, "video_count": 1,
                "concurrency_cap": 4, "script_brief": ""}},
    {"name": "Review chuẩn 9:16", "type_key": "product_review",
     "params": {"aspect_ratio": "9:16", "scene_count": 4, "quality": "standard",
                "crossfade_sec": 0.4, "audio_enabled": True, "video_count": 2,
                "concurrency_cap": 4, "script_brief": ""}},
]


def create_template(*, name: str, type_key: str, params: dict,
                    is_builtin: bool = False, position: int = 0) -> VideoPipelineTemplate:
    with get_session() as s:
        row = VideoPipelineTemplate(name=name, type_key=type_key, params=params,
                                    is_builtin=is_builtin, position=position)
        s.add(row)
        s.commit()
        s.refresh(row)
        return row


def list_templates() -> list[VideoPipelineTemplate]:
    with get_session() as s:
        rows = s.exec(
            select(VideoPipelineTemplate).order_by(
                VideoPipelineTemplate.position, VideoPipelineTemplate.id)
        ).all()
        return list(rows)


def _get(s, template_id: int) -> VideoPipelineTemplate:
    row = s.get(VideoPipelineTemplate, template_id)
    if row is None:
        raise TemplateNotFoundError(str(template_id))
    return row


def update_template(template_id: int, *, name: Optional[str] = None,
                    params: Optional[dict] = None,
                    position: Optional[int] = None) -> VideoPipelineTemplate:
    with get_session() as s:
        row = _get(s, template_id)
        if row.is_builtin:
            raise TemplateProtectedError(str(template_id))
        if name is not None:
            row.name = name
        if params is not None:
            row.params = params
        if position is not None:
            row.position = position
        row.updated_at = _utcnow()
        s.add(row)
        s.commit()
        s.refresh(row)
        return row


def delete_template(template_id: int) -> None:
    with get_session() as s:
        row = _get(s, template_id)
        if row.is_builtin:
            raise TemplateProtectedError(str(template_id))
        s.delete(row)
        s.commit()


def seed_builtins() -> None:
    """Idempotent: insert builtin templates only if not already present."""
    with get_session() as s:
        existing = {
            r.name for r in s.exec(
                select(VideoPipelineTemplate).where(
                    VideoPipelineTemplate.is_builtin == True)  # noqa: E712
            ).all()
        }
    for i, spec in enumerate(_BUILTINS):
        if spec["name"] not in existing:
            create_template(name=spec["name"], type_key=spec["type_key"],
                            params=spec["params"], is_builtin=True, position=i)
```

Run: `cd agent && python -m pytest tests/test_video_pipeline_templates.py -q`. Expect pass.

- [ ] **Step 3: Commit**

```bash
git add agent/flowboard/services/video_pipeline/templates.py agent/tests/test_video_pipeline_templates.py
git commit -m "feat(video-pipeline): template CRUD service + idempotent builtin seeding"
```

---

### Task 1.7: API routes — `/types` + `/templates` CRUD

**Files:**
- Create: `agent/flowboard/routes/video_pipeline.py`
- Modify: `agent/flowboard/main.py` (register router + seed builtins at startup)
- Create: `agent/tests/test_video_pipeline_routes_phase1.py`

- [ ] **Step 1: Write the failing test**

Write to `agent/tests/test_video_pipeline_routes_phase1.py`:

```python
def test_list_types(client):
    r = client.get("/api/video-pipeline/types")
    assert r.status_code == 200
    body = r.json()
    assert any(t["key"] == "product_review" for t in body)


def test_template_crud_flow(client):
    r = client.post("/api/video-pipeline/templates", json={
        "name": "T1", "type_key": "product_review", "params": {"scene_count": 3}})
    assert r.status_code == 201, r.text
    tid = r.json()["id"]

    r = client.get("/api/video-pipeline/templates")
    assert r.status_code == 200
    assert any(t["id"] == tid for t in r.json())

    r = client.patch(f"/api/video-pipeline/templates/{tid}",
                     json={"name": "T1-renamed"})
    assert r.status_code == 200
    assert r.json()["name"] == "T1-renamed"

    r = client.delete(f"/api/video-pipeline/templates/{tid}")
    assert r.status_code == 204


def test_builtin_template_protected(client):
    from flowboard.services.video_pipeline import templates
    t = templates.create_template(name="B", type_key="product_review",
                                  params={}, is_builtin=True)
    r = client.patch(f"/api/video-pipeline/templates/{t.id}", json={"name": "x"})
    assert r.status_code == 403
    r = client.delete(f"/api/video-pipeline/templates/{t.id}")
    assert r.status_code == 403


def test_patch_missing_template_404(client):
    r = client.patch("/api/video-pipeline/templates/987654", json={"name": "x"})
    assert r.status_code == 404
```

Run: `cd agent && python -m pytest tests/test_video_pipeline_routes_phase1.py -q`. Expect 404s (route not mounted).

- [ ] **Step 2: Implement the router**

Write to `agent/flowboard/routes/video_pipeline.py`:

```python
"""Video Pipeline HTTP API. Phase 1 surface: /types + /templates CRUD.
Later phases extend this same router (inputs/resolve, runs, regen, ...)."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from flowboard.services.video_pipeline.types import registry
from flowboard.services.video_pipeline import templates as tpl

router = APIRouter(prefix="/api/video-pipeline", tags=["video-pipeline"])


@router.get("/types")
def list_types():
    return registry.list_types()


class TemplateCreate(BaseModel):
    name: str
    type_key: str = "product_review"
    params: dict = {}


class TemplatePatch(BaseModel):
    name: Optional[str] = None
    params: Optional[dict] = None
    position: Optional[int] = None


def _serialize(t) -> dict:
    return {
        "id": t.id, "name": t.name, "type_key": t.type_key, "params": t.params,
        "is_builtin": t.is_builtin, "position": t.position,
        "created_at": t.created_at, "updated_at": t.updated_at,
    }


@router.get("/templates")
def list_templates():
    return [_serialize(t) for t in tpl.list_templates()]


@router.post("/templates", status_code=201)
def create_template(body: TemplateCreate):
    row = tpl.create_template(name=body.name, type_key=body.type_key, params=body.params)
    return _serialize(row)


@router.patch("/templates/{template_id}")
def patch_template(template_id: int, body: TemplatePatch):
    try:
        row = tpl.update_template(template_id, name=body.name, params=body.params,
                                  position=body.position)
    except tpl.TemplateNotFoundError:
        raise HTTPException(status_code=404, detail="template not found")
    except tpl.TemplateProtectedError:
        raise HTTPException(status_code=403, detail="builtin template is read-only")
    return _serialize(row)


@router.delete("/templates/{template_id}", status_code=204)
def delete_template(template_id: int):
    try:
        tpl.delete_template(template_id)
    except tpl.TemplateNotFoundError:
        raise HTTPException(status_code=404, detail="template not found")
    except tpl.TemplateProtectedError:
        raise HTTPException(status_code=403, detail="builtin template is read-only")
    return None
```

- [ ] **Step 3: Register router + seed builtins in `main.py`**

In `agent/flowboard/main.py`, add the import alongside the other route imports:

```python
from flowboard.routes import video_pipeline as video_pipeline_route
```

Add registration alongside the other `app.include_router(...)` calls:

```python
app.include_router(video_pipeline_route.router)
```

In the existing `lifespan` startup section (where `init_db()` / table setup runs), seed builtins after the DB is ready:

```python
from flowboard.services.video_pipeline import templates as _vp_templates
_vp_templates.seed_builtins()
```

> Place the seed call after `init_db()` so tables exist. `seed_builtins()` is idempotent. In tests the autouse `_fresh_db` fixture wipes tables per-test, so route tests that need a builtin create one explicitly (as in `test_builtin_template_protected`).

Run: `cd agent && python -m pytest tests/test_video_pipeline_routes_phase1.py -q`. Expect pass. Then run the whole suite: `python -m pytest -q`.

- [ ] **Step 4: Commit**

```bash
git add agent/flowboard/routes/video_pipeline.py agent/flowboard/main.py agent/tests/test_video_pipeline_routes_phase1.py
git commit -m "feat(video-pipeline): /types + /templates CRUD routes + builtin seeding"
```

---

### Task 1.8: Frontend routing + sidebar entry + placeholder pages

**Files:**
- Modify: `frontend/package.json` (add `react-router-dom`)
- Modify: `frontend/src/main.tsx` (wrap in `<BrowserRouter>`)
- Modify: `frontend/src/App.tsx` (route the canvas vs. pipeline pages)
- Create: `frontend/src/video-pipeline/pages/PipelineNewPage.tsx` (placeholder)
- Create: `frontend/src/video-pipeline/pages/PipelineRunsPage.tsx` (placeholder)
- Create: `frontend/src/video-pipeline/pages/PipelineRunDetailPage.tsx` (placeholder)
- Modify: `frontend/src/components/ProjectSidebar.tsx` (add "Video Pipeline" nav entry)

> No frontend test runner exists yet (added in Phase 7). Verification here is manual: `npm run lint` (type-check) passes and the dev server renders each route. The pages are intentionally placeholders filled in by Phases 2/4.

- [ ] **Step 1: Install react-router-dom**

From `frontend/`:
```bash
npm install react-router-dom@^6.26.0
```

- [ ] **Step 2: Wrap app in BrowserRouter**

In `frontend/src/main.tsx`, wrap `<App />`:

```tsx
import { BrowserRouter } from "react-router-dom";
// ...
ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </React.StrictMode>,
);
```

- [ ] **Step 3: Route canvas vs pipeline in App.tsx**

In `frontend/src/App.tsx`, introduce routes. Keep the existing canvas markup intact by extracting the current `canvas-wrap` contents (ReactFlowProvider + Board + Toolbar + dialogs) verbatim into a local `CanvasWrap` component mounted at `/`. The sidebar stays rendered across routes.

```tsx
import { Routes, Route } from "react-router-dom";
import { PipelineNewPage } from "./video-pipeline/pages/PipelineNewPage";
import { PipelineRunsPage } from "./video-pipeline/pages/PipelineRunsPage";
import { PipelineRunDetailPage } from "./video-pipeline/pages/PipelineRunDetailPage";

// Inside App's returned JSX:
//   <ProjectSidebar />
//   <Routes>
//     <Route path="/" element={<CanvasWrap/>} />
//     <Route path="/video-pipeline/new" element={<PipelineNewPage/>} />
//     <Route path="/video-pipeline/runs" element={<PipelineRunsPage/>} />
//     <Route path="/video-pipeline/runs/:shortId" element={<PipelineRunDetailPage/>} />
//   </Routes>
```

Do not change canvas internals — only relocate them into `CanvasWrap`.

- [ ] **Step 4: Create the three placeholder pages**

Write to `frontend/src/video-pipeline/pages/PipelineNewPage.tsx`:

```tsx
export function PipelineNewPage() {
  return (
    <div className="vp-page" data-testid="vp-new-page">
      <h1>Tạo Video Pipeline</h1>
      <p>Wizard sẽ hiển thị ở đây (Phase 2).</p>
    </div>
  );
}
```

Write to `frontend/src/video-pipeline/pages/PipelineRunsPage.tsx`:

```tsx
export function PipelineRunsPage() {
  return (
    <div className="vp-page" data-testid="vp-runs-page">
      <h1>Danh sách Run</h1>
      <p>Danh sách run + ResumeBanner (Phase 6).</p>
    </div>
  );
}
```

Write to `frontend/src/video-pipeline/pages/PipelineRunDetailPage.tsx`:

```tsx
import { useParams } from "react-router-dom";

export function PipelineRunDetailPage() {
  const { shortId } = useParams<{ shortId: string }>();
  return (
    <div className="vp-page" data-testid="vp-run-detail-page">
      <h1>Run {shortId}</h1>
      <p>Trang tiến độ (Phase 4).</p>
    </div>
  );
}
```

- [ ] **Step 5: Add the sidebar nav entry**

In `frontend/src/components/ProjectSidebar.tsx`, import `useNavigate` and `useLocation` from `react-router-dom`. Add a "Video Pipeline" entry near the board list header that calls `navigate("/video-pipeline/new")`, with active-state highlight when `location.pathname.startsWith("/video-pipeline")`. Reuse existing BEM classes; add a `.project-sidebar__nav-vp` rule in `frontend/src/styles.css` only if needed.

- [ ] **Step 6: Manual verify + lint**

```bash
cd frontend && npm run lint
```
Then `npm run dev`: confirm `/` renders the canvas unchanged; the "Video Pipeline" entry navigates to `/video-pipeline/new`; visiting `/video-pipeline/runs` and `/video-pipeline/runs/abc` render their placeholders.

- [ ] **Step 7: Commit**

```bash
git add frontend/package.json frontend/package-lock.json frontend/src/main.tsx frontend/src/App.tsx frontend/src/video-pipeline/ frontend/src/components/ProjectSidebar.tsx frontend/src/styles.css
git commit -m "feat(video-pipeline): frontend routing + sidebar entry + placeholder pages"
```

---

## Phase 2 — Wizard inputs + input resolver + run creation

**Outcome:** A user can fill the wizard (character + ≥1 product + background + script brief + params), each input resolved to a `media_id` via `/inputs/resolve` (upload / gen / ai_gen), then "Bắt đầu" creates a run with all product/video/scene rows via `POST /runs`. The progress page can fetch run detail via `GET /runs/{sid}`. The orchestrator itself is Phase 4 — `POST /runs/{sid}/start` is stubbed here to just mark the run and return 202 so the wizard→detail navigation works.

### Task 2.1: Input resolver service

Resolves one wizard input (character, a product, or background) into a `media_id`, from one of three sources: `upload` (already uploaded → media_id passed through), `gen` (prompt → `gen_image`; wizard does 4 variants then passes chosen media_id, so resolver mainly validates), `ai_gen` (short description → LLM expands to full prompt → `gen_image`). The resolver supports two entry points: `resolve_passthrough(media_id)` (validates a client-chosen media_id) and `resolve_ai_gen(description, project_id, aspect_ratio)` (LLM→gen_image, returns variants).

**Files:**
- Create: `agent/flowboard/services/video_pipeline/input_resolver.py`
- Create: `agent/tests/test_video_pipeline_input_resolver.py`

- [ ] **Step 1: Write the failing test**

Write to `agent/tests/test_video_pipeline_input_resolver.py`:

```python
import pytest

from flowboard.services.video_pipeline import input_resolver as ir


def test_aspect_ratio_mapping():
    assert ir.to_image_aspect("9:16") == "IMAGE_ASPECT_RATIO_PORTRAIT"
    assert ir.to_image_aspect("16:9") == "IMAGE_ASPECT_RATIO_LANDSCAPE"
    assert ir.to_image_aspect("1:1") == "IMAGE_ASPECT_RATIO_SQUARE"
    assert ir.to_image_aspect("weird") == "IMAGE_ASPECT_RATIO_LANDSCAPE"


@pytest.mark.asyncio
async def test_resolve_ai_gen_calls_llm_then_gen_image():
    calls = {}

    async def fake_llm(provider, user_prompt, *, system_prompt=None, attachments=None, timeout=90.0):
        calls["llm_prompt"] = user_prompt
        return "A cinematic full-body portrait of a friendly host, studio lighting."

    class FakeSDK:
        async def gen_image(self, prompt, project_id, aspect_ratio, ref_media_ids, variant_count, paygate_tier=None):
            calls["gen_prompt"] = prompt
            calls["variant_count"] = variant_count
            return {"media_ids": ["m1", "m2", "m3", "m4"],
                    "media_entries": [{"media_id": f"m{i}", "url": f"http://x/{i}"} for i in range(1, 5)]}

    out = await ir.resolve_ai_gen(
        description="thân thiện, áo thun trắng",
        project_id="proj_1",
        aspect_ratio="9:16",
        variant_count=4,
        llm_runner=fake_llm,
        sdk=FakeSDK(),
    )
    assert out["media_ids"] == ["m1", "m2", "m3", "m4"]
    assert len(out["media_entries"]) == 4
    assert "friendly host" in calls["gen_prompt"]
    assert calls["variant_count"] == 4


@pytest.mark.asyncio
async def test_resolve_ai_gen_surfaces_gen_error():
    async def fake_llm(*a, **k):
        return "prompt"

    class FailSDK:
        async def gen_image(self, **k):
            return {"error": "rate_limited"}

    with pytest.raises(ir.InputResolveError):
        await ir.resolve_ai_gen(description="x", project_id="p", aspect_ratio="1:1",
                                variant_count=4, llm_runner=fake_llm, sdk=FailSDK())
```

> The suite uses `pytest-asyncio`. Confirm it's configured (look for `asyncio_mode` in `pytest.ini`/`pyproject.toml`/`setup.cfg`, or existing `@pytest.mark.asyncio` usage in `agent/tests/`). If async tests use a different style (e.g. `anyio`), match that convention instead.

- [ ] **Step 2: Implement the resolver**

Write to `agent/flowboard/services/video_pipeline/input_resolver.py`:

```python
"""Resolve a wizard input (character / product / background) to a media_id.

Sources:
  - upload : client already uploaded via /api/upload; we pass media_id through.
  - gen    : client ran gen_image (4 variants) and chose one; pass-through too.
  - ai_gen : short description -> LLM expands to a full image prompt -> gen_image.

LLM + SDK are injected for testability (default to the real singletons).
"""
from __future__ import annotations

from typing import Any, Callable, Optional

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
    llm_runner: Optional[Callable[..., Any]] = None,
    sdk: Any = None,
) -> dict:
    llm_runner = llm_runner or run_llm
    sdk = sdk or get_flow_sdk()
    full_prompt = (await llm_runner(
        "claude", description, system_prompt=_AI_GEN_SYSTEM, timeout=60.0
    )).strip()
    if not full_prompt:
        raise InputResolveError("LLM returned empty prompt")
    resp = await sdk.gen_image(
        prompt=full_prompt,
        project_id=project_id,
        aspect_ratio=to_image_aspect(aspect_ratio),
        ref_media_ids=None,
        variant_count=variant_count,
    )
    if resp.get("error"):
        raise InputResolveError(str(resp["error"]))
    return {
        "prompt": full_prompt,
        "media_ids": resp.get("media_ids") or [],
        "media_entries": resp.get("media_entries") or [],
    }
```

> Provider name: the test injects `fake_llm`, so the literal `"claude"` is only used in production. Confirm `"claude"` is a registered provider key in `services/llm` (the registry `run_llm` dispatches on). If the default key differs (e.g. `"default"`), use that.

Run: `cd agent && python -m pytest tests/test_video_pipeline_input_resolver.py -q`. Expect pass.

- [ ] **Step 3: Commit**

```bash
git add agent/flowboard/services/video_pipeline/input_resolver.py agent/tests/test_video_pipeline_input_resolver.py
git commit -m "feat(video-pipeline): input resolver (ai_gen + aspect mapping)"
```

---

### Task 2.2: Run-builder service (create run + product/video/scene rows)

Given resolved inputs, create the `VideoPipelineRun` plus N product rows, N×n video rows, and N×n×M scene rows — all in one transaction. This is the data backbone the orchestrator later fills in.

**Files:**
- Create: `agent/flowboard/services/video_pipeline/run_builder.py`
- Create: `agent/tests/test_video_pipeline_run_builder.py`

- [ ] **Step 1: Write the failing test**

Write to `agent/tests/test_video_pipeline_run_builder.py`:

```python
from sqlmodel import select

from flowboard.db.session import get_session
from flowboard.db.video_pipeline_models import (
    VideoPipelineRun, VideoPipelineProduct, VideoPipelineVideo, VideoPipelineScene,
)
from flowboard.services.video_pipeline import run_builder


def _sample_inputs():
    return {
        "character": {"source": "upload", "media_id": "char_m"},
        "background": {"source": "upload", "media_id": "bg_m"},
        "products": [
            {"source": "upload", "media_id": "p0_m"},
            {"source": "upload", "media_id": "p1_m"},
        ],
        "script_brief": "Giới thiệu sản phẩm vui nhộn",
        "aspect_ratio": "9:16",
        "video_count": 2,
        "scene_count": 3,
        "quality": "standard",
        "crossfade_sec": 0.4,
        "audio_enabled": True,
        "concurrency_cap": 4,
    }


def test_create_run_builds_full_tree():
    run = run_builder.create_run(type_key="product_review", inputs=_sample_inputs())
    assert run.short_id.startswith("vpr_")
    assert run.status == "pending"

    with get_session() as s:
        rid = run.id
        products = s.exec(select(VideoPipelineProduct).where(
            VideoPipelineProduct.run_id == rid)).all()
        videos = s.exec(select(VideoPipelineVideo).where(
            VideoPipelineVideo.run_id == rid)).all()
        scenes = s.exec(select(VideoPipelineScene).where(
            VideoPipelineScene.run_id == rid)).all()

    assert len(products) == 2
    assert len(videos) == 2 * 2
    assert len(scenes) == 2 * 2 * 3


def test_create_run_requires_at_least_one_product():
    import pytest
    bad = _sample_inputs()
    bad["products"] = []
    with pytest.raises(run_builder.RunValidationError):
        run_builder.create_run(type_key="product_review", inputs=bad)


def test_create_run_rejects_unknown_type():
    import pytest
    with pytest.raises(run_builder.RunValidationError):
        run_builder.create_run(type_key="nope", inputs=_sample_inputs())


def test_video_count_clamped_1_to_4():
    import pytest
    bad = _sample_inputs()
    bad["video_count"] = 9
    with pytest.raises(run_builder.RunValidationError):
        run_builder.create_run(type_key="product_review", inputs=bad)
```

- [ ] **Step 2: Implement the run builder**

Write to `agent/flowboard/services/video_pipeline/run_builder.py`:

```python
"""Create a VideoPipelineRun and its full product/video/scene row tree in
one transaction. Pure DB construction — no Flow calls (orchestrator fills
status/media later)."""
from __future__ import annotations

from typing import Any

from flowboard.db.session import get_session
from flowboard.db.video_pipeline_models import (
    VideoPipelineRun, VideoPipelineProduct, VideoPipelineVideo, VideoPipelineScene,
)
from flowboard.services.video_pipeline.ids import new_short_id
from flowboard.services.video_pipeline.types import registry


class RunValidationError(Exception):
    pass


def _validate(type_key: str, inputs: dict[str, Any]) -> None:
    try:
        registry.get(type_key)
    except KeyError:
        raise RunValidationError(f"unknown type_key: {type_key}")
    products = inputs.get("products") or []
    if not products:
        raise RunValidationError("at least one product required")
    vc = int(inputs.get("video_count", 1))
    if not (1 <= vc <= 4):
        raise RunValidationError("video_count must be 1..4")
    sc = int(inputs.get("scene_count", 3))
    if not (1 <= sc <= 8):
        raise RunValidationError("scene_count must be 1..8")
    for key in ("character", "background"):
        if not (inputs.get(key) or {}).get("media_id"):
            raise RunValidationError(f"{key}.media_id required")


def create_run(*, type_key: str, inputs: dict[str, Any]) -> VideoPipelineRun:
    _validate(type_key, inputs)
    products = inputs["products"]
    video_count = int(inputs["video_count"])
    scene_count = int(inputs["scene_count"])

    with get_session() as s:
        run = VideoPipelineRun(short_id=new_short_id(), type_key=type_key, inputs=inputs)
        s.add(run)
        s.commit()
        s.refresh(run)
        rid = run.id

        for pi, prod in enumerate(products):
            s.add(VideoPipelineProduct(
                run_id=rid, product_index=pi,
                source=prod.get("source", "upload"),
                media_id=prod.get("media_id"),
                prompt=prod.get("prompt"),
            ))
            for vi in range(video_count):
                s.add(VideoPipelineVideo(run_id=rid, product_index=pi, video_index=vi))
                for sj in range(scene_count):
                    s.add(VideoPipelineScene(
                        run_id=rid, product_index=pi, video_index=vi, scene_index=sj))
        s.commit()
        s.refresh(run)
        return run
```

Run: `cd agent && python -m pytest tests/test_video_pipeline_run_builder.py -q`. Expect pass.

- [ ] **Step 3: Commit**

```bash
git add agent/flowboard/services/video_pipeline/run_builder.py agent/tests/test_video_pipeline_run_builder.py
git commit -m "feat(video-pipeline): run builder (run + product/video/scene rows)"
```

---

### Task 2.3: Run-detail serializer (used by polling + manifest)

A single function that loads a run + all children and returns the nested dict the frontend polls and the manifest stores. Centralizing it keeps the API response and `manifest.json` in sync.

**Files:**
- Create: `agent/flowboard/services/video_pipeline/serializers.py`
- Create: `agent/tests/test_video_pipeline_serializers.py`

- [ ] **Step 1: Write the failing test**

Write to `agent/tests/test_video_pipeline_serializers.py`:

```python
from flowboard.services.video_pipeline import run_builder, serializers


def _inputs():
    return {
        "character": {"source": "upload", "media_id": "char_m"},
        "background": {"source": "upload", "media_id": "bg_m"},
        "products": [{"source": "upload", "media_id": "p0_m"}],
        "script_brief": "x", "aspect_ratio": "9:16",
        "video_count": 1, "scene_count": 2,
    }


def test_serialize_run_nested_shape():
    run = run_builder.create_run(type_key="product_review", inputs=_inputs())
    dto = serializers.serialize_run(run.short_id)
    assert dto["short_id"] == run.short_id
    assert dto["status"] == "pending"
    assert len(dto["products"]) == 1
    prod = dto["products"][0]
    assert len(prod["videos"]) == 1
    assert len(prod["videos"][0]["scenes"]) == 2
    assert dto["progress"]["clips_total"] == 2
    assert dto["progress"]["clips_done"] == 0


def test_serialize_missing_returns_none():
    assert serializers.serialize_run("vpr_missing") is None
```

- [ ] **Step 2: Implement the serializer**

Write to `agent/flowboard/services/video_pipeline/serializers.py`:

```python
"""Load a run + children into the nested dict used by the polling API and
manifest.json. Single source of truth so both stay identical."""
from __future__ import annotations

from typing import Any, Optional

from sqlmodel import select

from flowboard.db.session import get_session
from flowboard.db.video_pipeline_models import (
    VideoPipelineRun, VideoPipelineProduct, VideoPipelineVideo, VideoPipelineScene,
)


def _scene_dto(sc: VideoPipelineScene) -> dict[str, Any]:
    return {
        "id": sc.id, "scene_index": sc.scene_index,
        "image_prompt": sc.image_prompt, "video_prompt": sc.video_prompt,
        "storyboard_media_id": sc.storyboard_media_id,
        "clip_media_id": sc.clip_media_id,
        "status": sc.status, "error": sc.error,
    }


def _video_dto(v: VideoPipelineVideo, scenes: list[VideoPipelineScene]) -> dict[str, Any]:
    return {
        "id": v.id, "video_index": v.video_index,
        "composite_media_id": v.composite_media_id,
        "merged_url": v.merged_url, "status": v.status, "error": v.error,
        "duration_sec": v.duration_sec, "file_size_bytes": v.file_size_bytes,
        "scenes": [_scene_dto(s) for s in sorted(scenes, key=lambda x: x.scene_index)],
    }


def serialize_run(short_id: str) -> Optional[dict[str, Any]]:
    with get_session() as s:
        run = s.exec(select(VideoPipelineRun).where(
            VideoPipelineRun.short_id == short_id)).first()
        if run is None:
            return None
        rid = run.id
        products = s.exec(select(VideoPipelineProduct).where(
            VideoPipelineProduct.run_id == rid)).all()
        videos = s.exec(select(VideoPipelineVideo).where(
            VideoPipelineVideo.run_id == rid)).all()
        scenes = s.exec(select(VideoPipelineScene).where(
            VideoPipelineScene.run_id == rid)).all()

    scenes_by_video: dict[tuple[int, int], list] = {}
    for sc in scenes:
        scenes_by_video.setdefault((sc.product_index, sc.video_index), []).append(sc)
    videos_by_product: dict[int, list] = {}
    for v in videos:
        videos_by_product.setdefault(v.product_index, []).append(v)

    product_dtos = []
    for p in sorted(products, key=lambda x: x.product_index):
        vids = sorted(videos_by_product.get(p.product_index, []), key=lambda x: x.video_index)
        product_dtos.append({
            "id": p.id, "product_index": p.product_index,
            "media_id": p.media_id, "source": p.source,
            "videos": [_video_dto(v, scenes_by_video.get((p.product_index, v.video_index), []))
                       for v in vids],
        })

    clips_total = len(scenes)
    clips_done = sum(1 for sc in scenes if sc.status in ("clip_done", "merged"))
    return {
        "short_id": run.short_id, "type_key": run.type_key,
        "flow_project_id": run.flow_project_id, "inputs": run.inputs,
        "status": run.status, "error": run.error, "cancelled": run.cancelled,
        "created_at": run.created_at, "started_at": run.started_at,
        "finished_at": run.finished_at,
        "products": product_dtos,
        "progress": {"clips_total": clips_total, "clips_done": clips_done},
    }
```

Run: `cd agent && python -m pytest tests/test_video_pipeline_serializers.py -q`. Expect pass.

- [ ] **Step 3: Commit**

```bash
git add agent/flowboard/services/video_pipeline/serializers.py agent/tests/test_video_pipeline_serializers.py
git commit -m "feat(video-pipeline): run-detail serializer (polling + manifest source of truth)"
```

---

### Task 2.4: API routes — `/inputs/resolve`, `POST /runs`, `GET /runs/{sid}`, `POST /runs/{sid}/start` (stub)

**Files:**
- Modify: `agent/flowboard/routes/video_pipeline.py`
- Create: `agent/tests/test_video_pipeline_routes_phase2.py`

- [ ] **Step 1: Write the failing test**

Write to `agent/tests/test_video_pipeline_routes_phase2.py`:

```python
def _payload():
    return {
        "type_key": "product_review",
        "inputs": {
            "character": {"source": "upload", "media_id": "char_m"},
            "background": {"source": "upload", "media_id": "bg_m"},
            "products": [{"source": "upload", "media_id": "p0_m"}],
            "script_brief": "demo", "aspect_ratio": "9:16",
            "video_count": 1, "scene_count": 2,
        },
    }


def test_create_run_then_get_detail(client):
    r = client.post("/api/video-pipeline/runs", json=_payload())
    assert r.status_code == 201, r.text
    sid = r.json()["short_id"]

    r = client.get(f"/api/video-pipeline/runs/{sid}")
    assert r.status_code == 200
    dto = r.json()
    assert dto["status"] == "pending"
    assert len(dto["products"][0]["videos"][0]["scenes"]) == 2


def test_create_run_validation_error_returns_422(client):
    bad = _payload()
    bad["inputs"]["products"] = []
    r = client.post("/api/video-pipeline/runs", json=bad)
    assert r.status_code == 422


def test_get_missing_run_404(client):
    r = client.get("/api/video-pipeline/runs/vpr_nope")
    assert r.status_code == 404


def test_start_run_returns_202_and_sets_status(client):
    sid = client.post("/api/video-pipeline/runs", json=_payload()).json()["short_id"]
    r = client.post(f"/api/video-pipeline/runs/{sid}/start")
    assert r.status_code == 202
    dto = client.get(f"/api/video-pipeline/runs/{sid}").json()
    assert dto["status"] in ("resolving", "generating", "done")


def test_resolve_passthrough_upload(client):
    r = client.post("/api/video-pipeline/inputs/resolve", json={
        "kind": "character", "source": "upload", "media_id": "abc",
        "aspect_ratio": "9:16"})
    assert r.status_code == 200
    assert r.json()["media_id"] == "abc"
```

- [ ] **Step 2: Extend the router**

Add to `agent/flowboard/routes/video_pipeline.py` (imports at top, routes appended):

```python
# --- add to imports ---
from fastapi import Response
from sqlmodel import select
from flowboard.services.video_pipeline import run_builder, serializers
from flowboard.services.video_pipeline import input_resolver as ir
from flowboard.db.session import get_session
from flowboard.db.video_pipeline_models import VideoPipelineRun


class ResolveBody(BaseModel):
    kind: str
    source: str
    media_id: Optional[str] = None
    description: Optional[str] = None
    project_id: Optional[str] = None
    aspect_ratio: str = "9:16"
    variant_count: int = 4


@router.post("/inputs/resolve")
async def resolve_input(body: ResolveBody):
    if body.source in ("upload", "gen"):
        if not body.media_id:
            raise HTTPException(status_code=422, detail="media_id required for this source")
        return {"media_id": body.media_id}
    if body.source == "ai_gen":
        if not (body.description and body.project_id):
            raise HTTPException(status_code=422, detail="description + project_id required")
        try:
            out = await ir.resolve_ai_gen(
                description=body.description, project_id=body.project_id,
                aspect_ratio=body.aspect_ratio, variant_count=body.variant_count)
        except ir.InputResolveError as e:
            raise HTTPException(status_code=502, detail=str(e))
        return out
    raise HTTPException(status_code=422, detail=f"unknown source: {body.source}")


class RunCreate(BaseModel):
    type_key: str = "product_review"
    inputs: dict


@router.post("/runs", status_code=201)
def create_run(body: RunCreate):
    try:
        run = run_builder.create_run(type_key=body.type_key, inputs=body.inputs)
    except run_builder.RunValidationError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return serializers.serialize_run(run.short_id)


@router.get("/runs/{short_id}")
def get_run(short_id: str):
    dto = serializers.serialize_run(short_id)
    if dto is None:
        raise HTTPException(status_code=404, detail="run not found")
    return dto


@router.post("/runs/{short_id}/start", status_code=202)
def start_run(short_id: str):
    # Phase 2 stub: validate exists, flip pending->resolving. Phase 4 replaces
    # this body with asyncio.create_task(orchestrator.run(run_id)).
    with get_session() as s:
        run = s.exec(select(VideoPipelineRun).where(
            VideoPipelineRun.short_id == short_id)).first()
        if run is None:
            raise HTTPException(status_code=404, detail="run not found")
        if run.status == "pending":
            run.status = "resolving"
            s.add(run)
            s.commit()
    return Response(status_code=202)
```

Run: `cd agent && python -m pytest tests/test_video_pipeline_routes_phase2.py -q`. Expect pass. Run full suite to confirm no regressions.

- [ ] **Step 3: Commit**

```bash
git add agent/flowboard/routes/video_pipeline.py agent/tests/test_video_pipeline_routes_phase2.py
git commit -m "feat(video-pipeline): /inputs/resolve + POST/GET runs + start stub"
```

---

### Task 2.5: Frontend API client functions + wizard store

**Files:**
- Modify: `frontend/src/api/client.ts` (add VP DTOs + endpoint functions)
- Create: `frontend/src/video-pipeline/store.ts` (Zustand wizard store)

> Still no test runner (Phase 7). Verify via `npm run lint`.

- [ ] **Step 1: Add DTOs + client functions**

In `frontend/src/api/client.ts`, add near the other DTOs/functions:

```typescript
// ---- Video Pipeline DTOs ----
export interface VPTypeDTO { key: string; label: string; input_schema: Record<string, unknown>; }
export interface VPTemplateDTO {
  id: number; name: string; type_key: string;
  params: Record<string, unknown>; is_builtin: boolean; position: number;
}
export interface VPSceneDTO {
  id: number; scene_index: number; image_prompt: string; video_prompt: string;
  storyboard_media_id: string | null; clip_media_id: string | null;
  status: string; error: string | null;
}
export interface VPVideoDTO {
  id: number; video_index: number; composite_media_id: string | null;
  merged_url: string | null; status: string; error: string | null;
  duration_sec: number | null; file_size_bytes: number | null; scenes: VPSceneDTO[];
}
export interface VPProductDTO {
  id: number; product_index: number; media_id: string | null;
  source: string; videos: VPVideoDTO[];
}
export interface VPRunDTO {
  short_id: string; type_key: string; flow_project_id: string | null;
  inputs: Record<string, unknown>; status: string; error: string | null;
  cancelled: boolean; products: VPProductDTO[];
  progress: { clips_total: number; clips_done: number };
}

// ---- Video Pipeline endpoints ----
export function vpListTypes() { return api<VPTypeDTO[]>("/api/video-pipeline/types"); }
export function vpListTemplates() { return api<VPTemplateDTO[]>("/api/video-pipeline/templates"); }
export function vpCreateTemplate(body: { name: string; type_key?: string; params: Record<string, unknown> }) {
  return api<VPTemplateDTO>("/api/video-pipeline/templates", { method: "POST", body: JSON.stringify(body) });
}
export function vpPatchTemplate(id: number, body: Partial<{ name: string; params: Record<string, unknown>; position: number }>) {
  return api<VPTemplateDTO>(`/api/video-pipeline/templates/${id}`, { method: "PATCH", body: JSON.stringify(body) });
}
export function vpDeleteTemplate(id: number) {
  return api<void>(`/api/video-pipeline/templates/${id}`, { method: "DELETE" });
}
export function vpResolveInput(body: {
  kind: string; source: string; media_id?: string;
  description?: string; project_id?: string; aspect_ratio?: string; variant_count?: number;
}) {
  return api<{ media_id?: string; media_ids?: string[]; media_entries?: Array<{ media_id: string; url: string }>; prompt?: string }>(
    "/api/video-pipeline/inputs/resolve", { method: "POST", body: JSON.stringify(body) });
}
export function vpCreateRun(body: { type_key: string; inputs: Record<string, unknown> }) {
  return api<VPRunDTO>("/api/video-pipeline/runs", { method: "POST", body: JSON.stringify(body) });
}
export function vpStartRun(shortId: string) {
  return fetch(`/api/video-pipeline/runs/${shortId}/start`, { method: "POST" }).then((r) => {
    if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  });
}
export function vpGetRun(shortId: string) { return api<VPRunDTO>(`/api/video-pipeline/runs/${shortId}`); }
```

> Match the file's existing `api<T>` import/style. `vpStartRun` returns 202 with an empty body, so it uses raw `fetch` (the `api<T>` helper calls `res.json()`, which would throw on an empty body).

- [ ] **Step 2: Create the wizard store**

Write to `frontend/src/video-pipeline/store.ts`:

```typescript
import { create } from "zustand";

export type InputSource = "upload" | "gen" | "ai_gen";

export interface ResolvedInput { source: InputSource; media_id: string | null; prompt?: string; }

export interface WizardState {
  typeKey: string;
  character: ResolvedInput;
  background: ResolvedInput;
  products: ResolvedInput[];
  scriptBrief: string;
  aspectRatio: "9:16" | "1:1" | "16:9";
  sceneCount: number;
  quality: "fast" | "standard" | "high";
  crossfadeSec: number;
  audioEnabled: boolean;
  videoCount: number;
  concurrencyCap: number;

  setField: <K extends keyof WizardState>(key: K, value: WizardState[K]) => void;
  setCharacter: (v: ResolvedInput) => void;
  setBackground: (v: ResolvedInput) => void;
  addProduct: () => void;
  removeProduct: (index: number) => void;
  setProduct: (index: number, v: ResolvedInput) => void;
  loadTemplateParams: (params: Record<string, unknown>) => void;
  reset: () => void;
  isValid: () => boolean;
}

const EMPTY_INPUT: ResolvedInput = { source: "upload", media_id: null };

const INITIAL = {
  typeKey: "product_review",
  character: { ...EMPTY_INPUT },
  background: { ...EMPTY_INPUT },
  products: [{ ...EMPTY_INPUT }],
  scriptBrief: "",
  aspectRatio: "9:16" as const,
  sceneCount: 3,
  quality: "standard" as const,
  crossfadeSec: 0.4,
  audioEnabled: true,
  videoCount: 2,
  concurrencyCap: 4,
};

export const useWizardStore = create<WizardState>((set, get) => ({
  ...INITIAL,
  setField: (key, value) => set({ [key]: value } as Partial<WizardState>),
  setCharacter: (v) => set({ character: v }),
  setBackground: (v) => set({ background: v }),
  addProduct: () => set((s) => ({ products: [...s.products, { ...EMPTY_INPUT }] })),
  removeProduct: (index) => set((s) => ({ products: s.products.filter((_, i) => i !== index) })),
  setProduct: (index, v) => set((s) => ({ products: s.products.map((p, i) => (i === index ? v : p)) })),
  loadTemplateParams: (params) =>
    set({
      aspectRatio: (params.aspect_ratio as WizardState["aspectRatio"]) ?? get().aspectRatio,
      sceneCount: (params.scene_count as number) ?? get().sceneCount,
      quality: (params.quality as WizardState["quality"]) ?? get().quality,
      crossfadeSec: (params.crossfade_sec as number) ?? get().crossfadeSec,
      audioEnabled: (params.audio_enabled as boolean) ?? get().audioEnabled,
      videoCount: (params.video_count as number) ?? get().videoCount,
      concurrencyCap: (params.concurrency_cap as number) ?? get().concurrencyCap,
      scriptBrief: (params.script_brief as string) ?? get().scriptBrief,
    }),
  reset: () => set({ ...INITIAL, products: [{ ...EMPTY_INPUT }] }),
  isValid: () => {
    const s = get();
    const ok = (i: ResolvedInput) => !!i.media_id;
    return ok(s.character) && ok(s.background) &&
      s.products.length >= 1 && s.products.every(ok) &&
      s.scriptBrief.trim().length > 0;
  },
}));

export function wizardToInputs(s: WizardState): Record<string, unknown> {
  return {
    character: { source: s.character.source, media_id: s.character.media_id, prompt: s.character.prompt },
    background: { source: s.background.source, media_id: s.background.media_id, prompt: s.background.prompt },
    products: s.products.map((p) => ({ source: p.source, media_id: p.media_id, prompt: p.prompt })),
    script_brief: s.scriptBrief,
    aspect_ratio: s.aspectRatio,
    video_count: s.videoCount,
    scene_count: s.sceneCount,
    quality: s.quality,
    crossfade_sec: s.crossfadeSec,
    audio_enabled: s.audioEnabled,
    concurrency_cap: s.concurrencyCap,
  };
}
```

- [ ] **Step 3: Lint + commit**

```bash
cd frontend && npm run lint
git add frontend/src/api/client.ts frontend/src/video-pipeline/store.ts
git commit -m "feat(video-pipeline): frontend API client + wizard zustand store"
```

---

### Task 2.6: `InputCard` component (3-tab: Upload / Gen / AI-gen)

**Files:**
- Create: `frontend/src/video-pipeline/components/InputCard.tsx`
- Modify: `frontend/src/styles.css` (InputCard styles)

> Component test deferred to Phase 7. Verify via lint + manual.

- [ ] **Step 1: Implement InputCard**

Write to `frontend/src/video-pipeline/components/InputCard.tsx`:

```tsx
import { useRef, useState } from "react";
import { uploadImage, vpResolveInput } from "../../api/client";
import { useGenerationStore } from "../../store/generation";
import type { ResolvedInput, InputSource } from "../store";

interface Props {
  label: string;
  kind: "character" | "product" | "background";
  value: ResolvedInput;
  aspectRatio: string;
  onChange: (v: ResolvedInput) => void;
}

const TABS: { key: InputSource; label: string }[] = [
  { key: "upload", label: "Upload" },
  { key: "gen", label: "Gen từ prompt" },
  { key: "ai_gen", label: "AI tạo" },
];

export function InputCard({ label, kind, value, aspectRatio, onChange }: Props) {
  const [tab, setTab] = useState<InputSource>(value.source);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [variants, setVariants] = useState<{ media_id: string; url: string }[]>([]);
  const [prompt, setPrompt] = useState(value.prompt ?? "");
  const fileRef = useRef<HTMLInputElement>(null);

  async function handleUpload(file: File) {
    setBusy(true); setError(null);
    try {
      const projectId = await useGenerationStore.getState().ensureProjectId();
      const resp = await uploadImage(file, projectId);
      onChange({ source: "upload", media_id: resp.media_id });
    } catch (e) {
      setError(e instanceof Error ? e.message : "upload failed");
    } finally { setBusy(false); }
  }

  async function handleAiGen() {
    setBusy(true); setError(null); setVariants([]);
    try {
      const projectId = await useGenerationStore.getState().ensureProjectId();
      const out = await vpResolveInput({
        kind, source: "ai_gen", description: prompt,
        project_id: projectId, aspect_ratio: aspectRatio, variant_count: 4,
      });
      setVariants(out.media_entries ?? []);
    } catch (e) {
      setError(e instanceof Error ? e.message : "generation failed");
    } finally { setBusy(false); }
  }

  function chooseVariant(mediaId: string) {
    onChange({ source: tab, media_id: mediaId, prompt });
  }

  return (
    <div className="vp-input-card" data-testid={`input-card-${kind}`}>
      <div className="vp-input-card__label">{label}</div>
      <div className="vp-input-card__tabs">
        {TABS.map((t) => (
          <button key={t.key} type="button"
            className={`vp-input-card__tab${tab === t.key ? " vp-input-card__tab--active" : ""}`}
            onClick={() => setTab(t.key)}>{t.label}</button>
        ))}
      </div>

      {tab === "upload" && (
        <div className="vp-input-card__body">
          <input ref={fileRef} type="file" accept="image/*" hidden
            onChange={(e) => { const f = e.target.files?.[0]; if (f) handleUpload(f); }} />
          <button type="button" disabled={busy} onClick={() => fileRef.current?.click()}>
            {busy ? "Đang tải..." : "Chọn ảnh"}
          </button>
        </div>
      )}

      {(tab === "gen" || tab === "ai_gen") && (
        <div className="vp-input-card__body">
          <textarea value={prompt} onChange={(e) => setPrompt(e.target.value)}
            placeholder={tab === "ai_gen" ? "Mô tả ngắn..." : "Prompt tạo ảnh..."} />
          <button type="button" disabled={busy || !prompt.trim()} onClick={handleAiGen}>
            {busy ? "Đang tạo..." : "Tạo 4 ảnh"}
          </button>
        </div>
      )}

      {variants.length > 0 && (
        <div className="vp-input-card__variants">
          {variants.map((v) => (
            <button key={v.media_id} type="button"
              className={`vp-input-card__variant${value.media_id === v.media_id ? " vp-input-card__variant--chosen" : ""}`}
              onClick={() => chooseVariant(v.media_id)}>
              <img src={`/media/${v.media_id}`} alt="variant" />
            </button>
          ))}
        </div>
      )}

      {value.media_id && (
        <div className="vp-input-card__chosen">
          <img src={`/media/${value.media_id}`} alt="chosen" />
        </div>
      )}
      {error && <div className="vp-input-card__error">{error}</div>}
    </div>
  );
}
```

> `gen` and `ai_gen` both call `vpResolveInput` with `source: "ai_gen"` here (LLM-assisted prompt). For pure `gen` (raw prompt verbatim, no LLM expansion), add a backend branch in `/inputs/resolve` for `source: "gen"` calling `gen_image` directly, and pass `source: tab`. v1 default: treat both as AI-assisted; revisit in Phase 7 polish.

- [ ] **Step 2: Add InputCard styles**

In `frontend/src/styles.css`, add `.vp-input-card*` rules using existing CSS variables (`--panel`, `--border`, `--accent`, `--error`). Tabs as a horizontal button row; variant/chosen images in a responsive grid. Follow BEM.

- [ ] **Step 3: Lint + commit**

```bash
cd frontend && npm run lint
git add frontend/src/video-pipeline/components/InputCard.tsx frontend/src/styles.css
git commit -m "feat(video-pipeline): InputCard 3-tab component"
```

---

### Task 2.7: Wizard page (compose inputs → create run → navigate)

**Files:**
- Modify: `frontend/src/video-pipeline/pages/PipelineNewPage.tsx` (replace placeholder)
- Modify: `frontend/src/styles.css` (wizard layout)

- [ ] **Step 1: Implement the wizard page**

Replace `frontend/src/video-pipeline/pages/PipelineNewPage.tsx` with the full wizard: vertical scroll, no stepper. Sections in order — pipeline-type dropdown (v1: only Product Review), `InputCard` for character, repeatable product `InputCard` list (+ Thêm / xóa, min 1), `InputCard` for background, script-brief textarea, video params (aspect ratio / scene count / quality / crossfade / audio toggle), video-count pills (1–4), advanced collapsible (concurrency cap), and the action row (💾 Lưu template, ▶ Bắt đầu) plus a 📂 Tải template button in the header.

Wire to the store and API:

```tsx
import { useNavigate } from "react-router-dom";
import { useWizardStore, wizardToInputs } from "../store";
import { InputCard } from "../components/InputCard";
import { vpCreateRun, vpStartRun } from "../../api/client";
import { useState } from "react";

export function PipelineNewPage() {
  const navigate = useNavigate();
  const s = useWizardStore();
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleStart() {
    if (!s.isValid()) { setError("Vui lòng điền đủ nhân vật, ≥1 sản phẩm, bối cảnh, prompt kịch bản."); return; }
    setSubmitting(true); setError(null);
    try {
      const run = await vpCreateRun({ type_key: s.typeKey, inputs: wizardToInputs(s) });
      await vpStartRun(run.short_id);
      navigate(`/video-pipeline/runs/${run.short_id}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Tạo run thất bại");
    } finally { setSubmitting(false); }
  }

  return (
    <div className="vp-page vp-wizard" data-testid="vp-new-page">
      {/* type dropdown, InputCards, params, pills, advanced — per section list above */}
      <div className="vp-wizard__actions">
        <button type="button" disabled={submitting || !s.isValid()} onClick={handleStart}
          data-testid="vp-start-btn">
          {submitting ? "Đang tạo..." : "▶ Bắt đầu"}
        </button>
      </div>
      {error && <div className="vp-wizard__error" role="alert">{error}</div>}
    </div>
  );
}
```

> "💾 Lưu template" calls `vpCreateTemplate({name, params})`; "📂 Tải template" opens a picker (`vpListTemplates` → `loadTemplateParams`). The full template-management modal (CRUD, builtin disabled) is fleshed out in Phase 7's UI-polish task; keep the "Bắt đầu" path complete here.

- [ ] **Step 2: Wizard styles + disabled state**

Add `.vp-wizard*` styles. The "Bắt đầu" button must set the `disabled` attribute when `submitting || !s.isValid()` — Phase 7 tests assert this.

- [ ] **Step 3: Lint + manual verify + commit**

```bash
cd frontend && npm run lint
```
Manual: fill inputs (Upload tab with a small image), confirm "Bắt đầu" enables only when valid, click → navigates to `/video-pipeline/runs/{sid}`.

```bash
git add frontend/src/video-pipeline/pages/PipelineNewPage.tsx frontend/src/styles.css
git commit -m "feat(video-pipeline): wizard page (compose inputs, create+start run, navigate)"
```

---

## Phase 3 — Type generation building blocks: `composite_gen` + `script_planner`

**Outcome:** Two pure, injectable, fully-tested service functions the orchestrator will call: `composite_gen` (character+product → n composite images via `gen_image` with refs) and `script_planner` (script brief + scene_count → validated per-scene JSON, with re-prompt-on-invalid retry). No orchestration yet — these are unit-level units with mocked Flow/LLM.

### Task 3.1: `composite_gen`

Generates the "ảnh gốc" composites for one product: `gen_image(prompt, refs=[character_media_id, product_media_id], variant_count=n)`. Returns one `media_entry` per video. Also persists results to the media cache via `ingest_urls` so `/media/{id}` serves them.

**Files:**
- Create: `agent/flowboard/services/video_pipeline/composite_gen.py`
- Create: `agent/tests/test_video_pipeline_composite_gen.py`

- [ ] **Step 1: Write the failing test**

Write to `agent/tests/test_video_pipeline_composite_gen.py`:

```python
import pytest

from flowboard.services.video_pipeline import composite_gen as cg


@pytest.mark.asyncio
async def test_generate_composites_passes_refs_and_count():
    seen = {}

    class FakeSDK:
        async def gen_image(self, prompt, project_id, aspect_ratio, ref_media_ids, variant_count, paygate_tier=None):
            seen["refs"] = ref_media_ids
            seen["count"] = variant_count
            seen["aspect"] = aspect_ratio
            return {"media_ids": ["c0", "c1"],
                    "media_entries": [{"media_id": "c0", "url": "u0"},
                                      {"media_id": "c1", "url": "u1"}]}

    ingested = {}
    def fake_ingest(entries):
        ingested["entries"] = entries

    out = await cg.generate_composites(
        character_media_id="char", product_media_id="prod",
        project_id="proj", aspect_ratio="9:16", variant_count=2,
        script_brief="vui nhộn", sdk=FakeSDK(), ingest=fake_ingest)

    assert seen["refs"] == ["char", "prod"]
    assert seen["count"] == 2
    assert seen["aspect"] == "IMAGE_ASPECT_RATIO_PORTRAIT"
    assert [e["media_id"] for e in out] == ["c0", "c1"]
    assert ingested["entries"]  # persisted for /media serving


@pytest.mark.asyncio
async def test_generate_composites_raises_on_error():
    class FailSDK:
        async def gen_image(self, **k):
            return {"error": "blocked"}

    with pytest.raises(cg.CompositeGenError):
        await cg.generate_composites(
            character_media_id="c", product_media_id="p", project_id="x",
            aspect_ratio="1:1", variant_count=1, script_brief="",
            sdk=FailSDK(), ingest=lambda e: None)


@pytest.mark.asyncio
async def test_generate_composites_raises_when_fewer_than_requested():
    class ShortSDK:
        async def gen_image(self, **k):
            return {"media_ids": ["only0"], "media_entries": [{"media_id": "only0", "url": "u"}]}

    with pytest.raises(cg.CompositeGenError):
        await cg.generate_composites(
            character_media_id="c", product_media_id="p", project_id="x",
            aspect_ratio="1:1", variant_count=3, script_brief="",
            sdk=ShortSDK(), ingest=lambda e: None)
```

- [ ] **Step 2: Implement composite_gen**

Write to `agent/flowboard/services/video_pipeline/composite_gen.py`:

```python
"""Generate composite (character + product) base images for a product.

gen_image with ref_media_ids=[character, product], variant_count=n.
One composite per video. Results are ingested into the media cache so the
frontend can serve them via /media/{id}.
"""
from __future__ import annotations

from typing import Any, Callable, Optional

from flowboard.services.flow_sdk import get_flow_sdk
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
    sdk: Any = None,
    ingest: Optional[Callable[[list[dict]], None]] = None,
) -> list[dict]:
    sdk = sdk or get_flow_sdk()
    ingest = ingest or media_service.ingest_urls

    resp = await sdk.gen_image(
        prompt=_PROMPT_TMPL.format(brief=script_brief or "n/a"),
        project_id=project_id,
        aspect_ratio=to_image_aspect(aspect_ratio),
        ref_media_ids=[character_media_id, product_media_id],
        variant_count=variant_count,
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
```

> `media_service.ingest_urls` is the same call `worker/processor.py` uses after `gen_image`. Verify the exact arg shape (list of `{media_id, url}` dicts) against `services/media.py` and match it.

Run: `cd agent && python -m pytest tests/test_video_pipeline_composite_gen.py -q`. Expect pass.

- [ ] **Step 3: Commit**

```bash
git add agent/flowboard/services/video_pipeline/composite_gen.py agent/tests/test_video_pipeline_composite_gen.py
git commit -m "feat(video-pipeline): composite_gen (char+product base images)"
```

---

### Task 3.2: `script_planner`

Given the script brief + scene_count + (optional) vision descriptions of the inputs, ask the LLM for a JSON array of M scenes, each `{image_prompt, video_prompt}`. Validate the JSON shape; on invalid output, re-prompt with feedback (max 2 retries). Each video gets an **independent** script (the orchestrator calls this once per video).

**Files:**
- Create: `agent/flowboard/services/video_pipeline/script_planner.py`
- Create: `agent/tests/test_video_pipeline_script_planner.py`

- [ ] **Step 1: Write the failing test**

Write to `agent/tests/test_video_pipeline_script_planner.py`:

```python
import json
import pytest

from flowboard.services.video_pipeline import script_planner as sp


def _valid_scenes(n):
    return json.dumps({"scenes": [
        {"image_prompt": f"compose scene {i}", "video_prompt": f"motion {i}"}
        for i in range(n)
    ]})


@pytest.mark.asyncio
async def test_plan_returns_validated_scenes():
    async def fake_llm(provider, user_prompt, *, system_prompt=None, attachments=None, timeout=90.0):
        return _valid_scenes(3)

    scenes = await sp.plan_script(script_brief="demo", scene_count=3, llm_runner=fake_llm)
    assert len(scenes) == 3
    assert scenes[0]["image_prompt"]
    assert scenes[0]["video_prompt"]


@pytest.mark.asyncio
async def test_plan_extracts_json_from_codefence():
    async def fake_llm(*a, **k):
        return "```json\n" + _valid_scenes(2) + "\n```"

    scenes = await sp.plan_script(script_brief="x", scene_count=2, llm_runner=fake_llm)
    assert len(scenes) == 2


@pytest.mark.asyncio
async def test_plan_reprompts_on_invalid_then_succeeds():
    calls = {"n": 0}

    async def flaky_llm(*a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            return "not json at all"
        return _valid_scenes(2)

    scenes = await sp.plan_script(script_brief="x", scene_count=2,
                                  llm_runner=flaky_llm, max_retries=2)
    assert len(scenes) == 2
    assert calls["n"] == 2  # retried once


@pytest.mark.asyncio
async def test_plan_raises_after_exhausting_retries():
    async def bad_llm(*a, **k):
        return "never valid"

    with pytest.raises(sp.ScriptPlanError):
        await sp.plan_script(script_brief="x", scene_count=2,
                             llm_runner=bad_llm, max_retries=2)


@pytest.mark.asyncio
async def test_plan_rejects_wrong_scene_count():
    async def short_llm(*a, **k):
        return _valid_scenes(1)  # asked for 3

    with pytest.raises(sp.ScriptPlanError):
        await sp.plan_script(script_brief="x", scene_count=3,
                             llm_runner=short_llm, max_retries=1)
```

- [ ] **Step 2: Implement script_planner**

Write to `agent/flowboard/services/video_pipeline/script_planner.py`:

```python
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
        raw = await llm_runner("claude", _build_prompt(script_brief, scene_count, feedback),
                               system_prompt=_SYSTEM, timeout=90.0)
        try:
            parsed = _extract_json(raw)
            return _validate(parsed, scene_count)
        except (json.JSONDecodeError, ValueError) as e:
            last_err = str(e)
            feedback = last_err
    raise ScriptPlanError(f"failed to produce valid script after {max_retries} attempts: {last_err}")
```

Run: `cd agent && python -m pytest tests/test_video_pipeline_script_planner.py -q`. Expect pass.

> The `test_plan_reprompts_on_invalid_then_succeeds` test uses `max_retries=2` and expects exactly 2 LLM calls (1 fail + 1 success). The loop runs up to `max_retries` iterations total — confirm the loop count semantics match (here: attempt 1 fails, attempt 2 succeeds → returns on iteration 2). If you prefer "1 initial + N retries", adjust both the loop and the test together.

- [ ] **Step 3: Commit**

```bash
git add agent/flowboard/services/video_pipeline/script_planner.py agent/tests/test_video_pipeline_script_planner.py
git commit -m "feat(video-pipeline): script_planner (per-video M-scene JSON + retry)"
```

---

## Phase 4 — Storyboard + clip generation + orchestrator + polling progress page

**Outcome:** End-to-end generation works. The orchestrator (idempotent, resume-safe, concurrency-capped) runs per product → per video → per scene, producing storyboards and clips. `POST /runs/{sid}/start` launches it as a background task. The progress page polls `GET /runs/{sid}` and renders live status. (Merging is Phase 5 — until then, videos reach `scenes_done`.)

### Task 4.1: `storyboard_gen`

One scene's storyboard: `gen_image(image_prompt, refs=[composite_media_id, background_media_id], variant_count=1)`. Returns one media entry; ingests for serving.

**Files:**
- Create: `agent/flowboard/services/video_pipeline/storyboard_gen.py`
- Create: `agent/tests/test_video_pipeline_storyboard_gen.py`

- [ ] **Step 1: Write the failing test**

Write to `agent/tests/test_video_pipeline_storyboard_gen.py`:

```python
import pytest

from flowboard.services.video_pipeline import storyboard_gen as sg


@pytest.mark.asyncio
async def test_generate_storyboard_uses_composite_and_background_refs():
    seen = {}

    class FakeSDK:
        async def gen_image(self, prompt, project_id, aspect_ratio, ref_media_ids, variant_count, paygate_tier=None):
            seen["refs"] = ref_media_ids
            seen["count"] = variant_count
            seen["prompt"] = prompt
            return {"media_entries": [{"media_id": "sb0", "url": "u"}], "media_ids": ["sb0"]}

    mid = await sg.generate_storyboard(
        image_prompt="wide shot", composite_media_id="comp", background_media_id="bg",
        project_id="proj", aspect_ratio="9:16", sdk=FakeSDK(), ingest=lambda e: None)

    assert seen["refs"] == ["comp", "bg"]
    assert seen["count"] == 1
    assert seen["prompt"] == "wide shot"
    assert mid == "sb0"


@pytest.mark.asyncio
async def test_generate_storyboard_error_raises():
    class FailSDK:
        async def gen_image(self, **k):
            return {"error": "filtered"}

    with pytest.raises(sg.StoryboardGenError):
        await sg.generate_storyboard(
            image_prompt="x", composite_media_id="c", background_media_id="b",
            project_id="p", aspect_ratio="1:1", sdk=FailSDK(), ingest=lambda e: None)
```

- [ ] **Step 2: Implement storyboard_gen**

Write to `agent/flowboard/services/video_pipeline/storyboard_gen.py`:

```python
"""One scene's storyboard image: gen_image with refs [composite, background]."""
from __future__ import annotations

from typing import Any, Callable, Optional

from flowboard.services.flow_sdk import get_flow_sdk
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
    sdk: Any = None,
    ingest: Optional[Callable[[list[dict]], None]] = None,
) -> str:
    sdk = sdk or get_flow_sdk()
    ingest = ingest or media_service.ingest_urls
    resp = await sdk.gen_image(
        prompt=image_prompt,
        project_id=project_id,
        aspect_ratio=to_image_aspect(aspect_ratio),
        ref_media_ids=[composite_media_id, background_media_id],
        variant_count=1,
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
```

Run: `cd agent && python -m pytest tests/test_video_pipeline_storyboard_gen.py -q`. Expect pass.

- [ ] **Step 3: Commit**

```bash
git add agent/flowboard/services/video_pipeline/storyboard_gen.py agent/tests/test_video_pipeline_storyboard_gen.py
git commit -m "feat(video-pipeline): storyboard_gen (composite+background -> scene image)"
```

---

### Task 4.2: `clip_gen` (i2v dispatch + poll until done)

Render one clip from a storyboard via `gen_video(start_media_id=storyboard, prompt=video_prompt)`, then poll `check_async` until the single operation is done (mirrors `worker/processor.py`). Returns the clip `media_id`. Poll interval/sleep are injectable so tests run instantly.

**Files:**
- Create: `agent/flowboard/services/video_pipeline/clip_gen.py`
- Create: `agent/tests/test_video_pipeline_clip_gen.py`

- [ ] **Step 1: Write the failing test**

Write to `agent/tests/test_video_pipeline_clip_gen.py`:

```python
import pytest

from flowboard.services.video_pipeline import clip_gen as cg


@pytest.mark.asyncio
async def test_clip_dispatch_then_poll_success():
    polls = {"n": 0}

    class FakeSDK:
        async def gen_video(self, prompt, project_id, start_media_id, aspect_ratio, video_quality=None, paygate_tier=None):
            assert start_media_id == "sb0"
            return {"operation_names": ["op1"]}

        async def check_async(self, operation_names, workflows=None):
            polls["n"] += 1
            if polls["n"] < 2:
                return {"operations": [{"name": "op1", "done": False}]}
            return {"operations": [{"name": "op1", "done": True,
                                    "media_entries": [{"media_id": "clip0", "url": "u"}]}]}

    async def no_sleep(_):
        return None

    mid = await cg.generate_clip(
        video_prompt="dolly in", start_media_id="sb0", project_id="proj",
        aspect_ratio="9:16", quality="standard",
        sdk=FakeSDK(), sleep=no_sleep, ingest=lambda e: None)
    assert mid == "clip0"
    assert polls["n"] == 2


@pytest.mark.asyncio
async def test_clip_dispatch_error_raises():
    class FailSDK:
        async def gen_video(self, **k):
            return {"error": "quota"}

    with pytest.raises(cg.ClipGenError):
        await cg.generate_clip(video_prompt="x", start_media_id="s", project_id="p",
                               aspect_ratio="1:1", quality="fast",
                               sdk=FailSDK(), sleep=None, ingest=lambda e: None)


@pytest.mark.asyncio
async def test_clip_per_op_error_raises():
    class FilterSDK:
        async def gen_video(self, **k):
            return {"operation_names": ["op1"]}
        async def check_async(self, operation_names, workflows=None):
            return {"operations": [{"name": "op1", "done": True, "error": "UNSAFE_GENERATION"}]}

    async def no_sleep(_): return None
    with pytest.raises(cg.ClipGenError):
        await cg.generate_clip(video_prompt="x", start_media_id="s", project_id="p",
                               aspect_ratio="1:1", quality="fast",
                               sdk=FilterSDK(), sleep=no_sleep, ingest=lambda e: None)


@pytest.mark.asyncio
async def test_clip_timeout_raises():
    class StuckSDK:
        async def gen_video(self, **k):
            return {"operation_names": ["op1"]}
        async def check_async(self, operation_names, workflows=None):
            return {"operations": [{"name": "op1", "done": False}]}

    async def no_sleep(_): return None
    with pytest.raises(cg.ClipGenError):
        await cg.generate_clip(video_prompt="x", start_media_id="s", project_id="p",
                               aspect_ratio="1:1", quality="fast", max_cycles=3,
                               sdk=StuckSDK(), sleep=no_sleep, ingest=lambda e: None)
```

- [ ] **Step 2: Implement clip_gen**

Write to `agent/flowboard/services/video_pipeline/clip_gen.py`:

```python
"""Render one i2v clip from a storyboard image. Dispatch via gen_video, then
poll check_async until the single operation resolves. Mirrors the contract in
worker/processor.py but scoped to one operation. sleep + sdk + ingest injected
so tests run with no real waiting."""
from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable, Optional

from flowboard.services.flow_sdk import get_flow_sdk
from flowboard.services import media as media_service

VIDEO_ASPECT = {
    "9:16": "VIDEO_ASPECT_RATIO_PORTRAIT",
    "16:9": "VIDEO_ASPECT_RATIO_LANDSCAPE",
    "1:1": "VIDEO_ASPECT_RATIO_SQUARE",
}

# Default poll cadence matches worker/processor.py.
_POLL_INTERVAL_S = 10.0
_POLL_MAX_CYCLES = 30


class ClipGenError(Exception):
    pass


def _to_video_aspect(aspect_ratio: str) -> str:
    return VIDEO_ASPECT.get(aspect_ratio, "VIDEO_ASPECT_RATIO_LANDSCAPE")


async def generate_clip(
    *,
    video_prompt: str,
    start_media_id: str,
    project_id: str,
    aspect_ratio: str,
    quality: str = "standard",
    sdk: Any = None,
    sleep: Optional[Callable[[float], Awaitable[None]]] = None,
    ingest: Optional[Callable[[list[dict]], None]] = None,
    interval_s: float = _POLL_INTERVAL_S,
    max_cycles: int = _POLL_MAX_CYCLES,
) -> str:
    sdk = sdk or get_flow_sdk()
    sleep = sleep or asyncio.sleep
    ingest = ingest or media_service.ingest_urls

    dispatch = await sdk.gen_video(
        prompt=video_prompt,
        project_id=project_id,
        start_media_id=start_media_id,
        aspect_ratio=_to_video_aspect(aspect_ratio),
        video_quality=quality,
    )
    if dispatch.get("error"):
        raise ClipGenError(str(dispatch["error"]))
    op_names = dispatch.get("operation_names") or []
    if not op_names:
        raise ClipGenError("no operations returned")
    workflows = dispatch.get("workflows") or None
    op = op_names[0]

    for _ in range(max_cycles):
        await sleep(interval_s)
        poll = await sdk.check_async(op_names, workflows=workflows)
        if poll.get("error"):
            continue
        for o in poll.get("operations") or []:
            if not isinstance(o, dict) or o.get("name") != op:
                continue
            err = o.get("error")
            if isinstance(err, str) and err:
                raise ClipGenError(err)
            if o.get("done"):
                for e in o.get("media_entries") or []:
                    if isinstance(e, dict) and e.get("media_id"):
                        if e.get("url"):
                            try:
                                ingest([e])
                            except Exception:  # noqa: BLE001
                                pass
                        return e["media_id"]
                raise ClipGenError("operation done but no media returned")
    raise ClipGenError("timeout_waiting_video")
```

Run: `cd agent && python -m pytest tests/test_video_pipeline_clip_gen.py -q`. Expect pass.

> Verify `gen_video`'s real `video_quality` accepted values (e.g. enum strings) in `flow_sdk.py`; map the wizard's `fast|standard|high` to whatever the SDK expects if they differ. If `paygate_tier` is required (the SDK raised `ValueError` without it in some paths), pass it through from the run/flow_client default as `worker/processor.py` does.

- [ ] **Step 3: Commit**

```bash
git add agent/flowboard/services/video_pipeline/clip_gen.py agent/tests/test_video_pipeline_clip_gen.py
git commit -m "feat(video-pipeline): clip_gen (i2v dispatch + poll to media_id)"
```

---

### Task 4.3: DB transition helpers (write status + manifest, guarded by state machine)

Small helpers the orchestrator uses to advance a scene/video/run, each: validate the transition via `state_machine`, write the new status + `updated_at`, and refresh `manifest.json`. Keeping them here makes the orchestrator readable and the transitions testable.

**Files:**
- Create: `agent/flowboard/services/video_pipeline/transitions.py`
- Create: `agent/tests/test_video_pipeline_transitions.py`

- [ ] **Step 1: Write the failing test**

Write to `agent/tests/test_video_pipeline_transitions.py`:

```python
import pytest
from sqlmodel import select

from flowboard.db.session import get_session
from flowboard.db.video_pipeline_models import VideoPipelineScene, VideoPipelineRun
from flowboard.services.video_pipeline import run_builder, transitions


def _make_run():
    return run_builder.create_run(type_key="product_review", inputs={
        "character": {"source": "upload", "media_id": "c"},
        "background": {"source": "upload", "media_id": "b"},
        "products": [{"source": "upload", "media_id": "p0"}],
        "script_brief": "x", "aspect_ratio": "9:16",
        "video_count": 1, "scene_count": 1,
    })


def test_set_scene_status_valid(monkeypatch, tmp_path):
    from flowboard.services.video_pipeline import storage
    monkeypatch.setattr(storage, "STORAGE_DIR", tmp_path)
    run = _make_run()
    with get_session() as s:
        sc = s.exec(select(VideoPipelineScene).where(
            VideoPipelineScene.run_id == run.id)).first()
        sid = sc.id

    transitions.set_scene_status(run.short_id, sid, "storyboard_running")
    with get_session() as s:
        sc = s.get(VideoPipelineScene, sid)
        assert sc.status == "storyboard_running"


def test_set_scene_status_invalid_raises(monkeypatch, tmp_path):
    from flowboard.services.video_pipeline import storage
    monkeypatch.setattr(storage, "STORAGE_DIR", tmp_path)
    run = _make_run()
    with get_session() as s:
        sc = s.exec(select(VideoPipelineScene).where(
            VideoPipelineScene.run_id == run.id)).first()
        sid = sc.id
    with pytest.raises(transitions.InvalidTransition):
        transitions.set_scene_status(run.short_id, sid, "merged")  # pending->merged illegal


def test_set_run_status_writes_manifest(monkeypatch, tmp_path):
    from flowboard.services.video_pipeline import storage
    monkeypatch.setattr(storage, "STORAGE_DIR", tmp_path)
    run = _make_run()
    transitions.set_run_status(run.short_id, "resolving")
    manifest = storage.read_manifest(run.short_id)
    assert manifest["status"] == "resolving"
```

- [ ] **Step 2: Implement transitions**

Write to `agent/flowboard/services/video_pipeline/transitions.py`:

```python
"""Guarded status writes for run/video/scene + manifest refresh. Every write
validates against the pure state machine first, then persists, then snapshots
the run into manifest.json (resume-safe)."""
from __future__ import annotations

from typing import Optional

from sqlmodel import select

from flowboard.db.session import get_session
from flowboard.db.models import _utcnow
from flowboard.db.video_pipeline_models import (
    VideoPipelineRun, VideoPipelineVideo, VideoPipelineScene,
)
from flowboard.services.video_pipeline import state_machine as sm
from flowboard.services.video_pipeline import storage, serializers


class InvalidTransition(Exception):
    pass


def _refresh_manifest(short_id: str) -> None:
    dto = serializers.serialize_run(short_id)
    if dto is not None:
        storage.write_manifest(short_id, dto)


def set_run_status(short_id: str, new_status: str, *, error: Optional[str] = None,
                   force: bool = False) -> None:
    with get_session() as s:
        run = s.exec(select(VideoPipelineRun).where(
            VideoPipelineRun.short_id == short_id)).first()
        if run is None:
            raise InvalidTransition(f"run {short_id} not found")
        if not force and run.status != new_status and not sm.can_transition_run(run.status, new_status):
            raise InvalidTransition(f"run {run.status} -> {new_status}")
        run.status = new_status
        if error is not None:
            run.error = error
        if new_status in ("done", "failed", "cancelled"):
            run.finished_at = _utcnow()
        if new_status == "resolving" and run.started_at is None:
            run.started_at = _utcnow()
        s.add(run)
        s.commit()
    _refresh_manifest(short_id)


def set_video_status(short_id: str, video_id: int, new_status: str, *,
                     error: Optional[str] = None, force: bool = False) -> None:
    with get_session() as s:
        v = s.get(VideoPipelineVideo, video_id)
        if v is None:
            raise InvalidTransition(f"video {video_id} not found")
        if not force and v.status != new_status and not sm.can_transition_video(v.status, new_status):
            raise InvalidTransition(f"video {v.status} -> {new_status}")
        v.status = new_status
        if error is not None:
            v.error = error
        v.updated_at = _utcnow()
        s.add(v)
        s.commit()
    _refresh_manifest(short_id)


def set_scene_status(short_id: str, scene_id: int, new_status: str, *,
                     error: Optional[str] = None, force: bool = False) -> None:
    with get_session() as s:
        sc = s.get(VideoPipelineScene, scene_id)
        if sc is None:
            raise InvalidTransition(f"scene {scene_id} not found")
        if not force and sc.status != new_status and not sm.can_transition_scene(sc.status, new_status):
            raise InvalidTransition(f"scene {sc.status} -> {new_status}")
        sc.status = new_status
        if error is not None:
            sc.error = error
        sc.updated_at = _utcnow()
        s.add(sc)
        s.commit()
    _refresh_manifest(short_id)
```

Run: `cd agent && python -m pytest tests/test_video_pipeline_transitions.py -q`. Expect pass.

- [ ] **Step 3: Commit**

```bash
git add agent/flowboard/services/video_pipeline/transitions.py agent/tests/test_video_pipeline_transitions.py
git commit -m "feat(video-pipeline): guarded transition helpers + manifest refresh"
```

---

### Task 4.4: Orchestrator (idempotent, resume-safe, concurrency-capped)

The heart of the feature. `run(short_id)` is an async coroutine that: ensures `flow_project_id`; resolves inputs (already media_ids in v1); per product generates composites; per video (under a shared semaphore) plans the script, writes scene prompts, then per scene generates storyboard → clip; advances all statuses through `transitions`. Idempotent: each step skips work already done (resume). Honors `run.cancelled`. Stops at `scenes_done` per video for now — Phase 5 adds the merge step.

**Files:**
- Create: `agent/flowboard/services/video_pipeline/orchestrator.py`
- Create: `agent/tests/test_video_pipeline_orchestrator.py`

- [ ] **Step 1: Write the failing test** (fully mocked Flow/LLM; deterministic)

Write to `agent/tests/test_video_pipeline_orchestrator.py`:

```python
import pytest
from sqlmodel import select

from flowboard.db.session import get_session
from flowboard.db.video_pipeline_models import (
    VideoPipelineRun, VideoPipelineVideo, VideoPipelineScene,
)
from flowboard.services.video_pipeline import run_builder, orchestrator


class FakeDeps:
    """Injected generation deps — deterministic, no network."""
    def __init__(self, fail_scene=None):
        self.fail_scene = fail_scene  # (product_index, video_index, scene_index) to fail clip
        self.composite_calls = 0

    async def ensure_project(self, run):
        return "proj_fake"

    async def gen_composites(self, **k):
        self.composite_calls += 1
        n = k["variant_count"]
        return [{"media_id": f"comp{i}", "url": "u"} for i in range(n)]

    async def plan_script(self, *, script_brief, scene_count):
        return [{"image_prompt": f"ip{j}", "video_prompt": f"vp{j}"} for j in range(scene_count)]

    async def gen_storyboard(self, **k):
        return f"sb-{k['composite_media_id']}"

    async def gen_clip(self, *, product_index, video_index, scene_index, **k):
        if self.fail_scene == (product_index, video_index, scene_index):
            from flowboard.services.video_pipeline.clip_gen import ClipGenError
            raise ClipGenError("blocked")
        return f"clip-{product_index}-{video_index}-{scene_index}"


def _make_run(products=1, videos=1, scenes=2):
    return run_builder.create_run(type_key="product_review", inputs={
        "character": {"source": "upload", "media_id": "c"},
        "background": {"source": "upload", "media_id": "b"},
        "products": [{"source": "upload", "media_id": f"p{i}"} for i in range(products)],
        "script_brief": "demo", "aspect_ratio": "9:16",
        "video_count": videos, "scene_count": scenes, "concurrency_cap": 2,
    })


@pytest.mark.asyncio
async def test_happy_path_all_scenes_clip_done(monkeypatch, tmp_path):
    from flowboard.services.video_pipeline import storage
    monkeypatch.setattr(storage, "STORAGE_DIR", tmp_path)
    run = _make_run(products=2, videos=2, scenes=3)
    deps = FakeDeps()
    await orchestrator.run(run.short_id, deps=deps)

    with get_session() as s:
        scenes = s.exec(select(VideoPipelineScene).where(
            VideoPipelineScene.run_id == run.id)).all()
        videos = s.exec(select(VideoPipelineVideo).where(
            VideoPipelineVideo.run_id == run.id)).all()
        run_row = s.get(VideoPipelineRun, run.id)

    assert len(scenes) == 2 * 2 * 3
    assert all(sc.status == "clip_done" for sc in scenes)
    assert all(sc.clip_media_id for sc in scenes)
    assert all(v.status == "scenes_done" for v in videos)
    assert all(v.composite_media_id for v in videos)
    # generating until merge lands in Phase 5
    assert run_row.status in ("generating", "merging")


@pytest.mark.asyncio
async def test_per_scene_failure_does_not_fail_run(monkeypatch, tmp_path):
    from flowboard.services.video_pipeline import storage
    monkeypatch.setattr(storage, "STORAGE_DIR", tmp_path)
    run = _make_run(products=1, videos=1, scenes=3)
    deps = FakeDeps(fail_scene=(0, 0, 1))
    await orchestrator.run(run.short_id, deps=deps)

    with get_session() as s:
        scenes = sorted(s.exec(select(VideoPipelineScene).where(
            VideoPipelineScene.run_id == run.id)).all(), key=lambda x: x.scene_index)
        run_row = s.get(VideoPipelineRun, run.id)

    assert scenes[0].status == "clip_done"
    assert scenes[1].status == "failed"
    assert scenes[2].status == "clip_done"
    assert run_row.status != "failed"


@pytest.mark.asyncio
async def test_resume_skips_completed_scenes(monkeypatch, tmp_path):
    from flowboard.services.video_pipeline import storage
    monkeypatch.setattr(storage, "STORAGE_DIR", tmp_path)
    run = _make_run(products=1, videos=1, scenes=2)
    deps = FakeDeps()
    await orchestrator.run(run.short_id, deps=deps)
    first_composites = deps.composite_calls

    # Re-run: idempotent, composites already present -> not regenerated.
    deps2 = FakeDeps()
    await orchestrator.run(run.short_id, deps=deps2)
    assert deps2.composite_calls == 0  # all videos already had composite_media_id


@pytest.mark.asyncio
async def test_cancel_stops_before_more_work(monkeypatch, tmp_path):
    from flowboard.services.video_pipeline import storage
    monkeypatch.setattr(storage, "STORAGE_DIR", tmp_path)
    run = _make_run(products=2, videos=1, scenes=2)
    with get_session() as s:
        r = s.get(VideoPipelineRun, run.id)
        r.cancelled = True
        s.add(r)
        s.commit()
    deps = FakeDeps()
    await orchestrator.run(run.short_id, deps=deps)
    with get_session() as s:
        run_row = s.get(VideoPipelineRun, run.id)
    assert run_row.status == "cancelled"
```

- [ ] **Step 2: Implement the orchestrator**

Write to `agent/flowboard/services/video_pipeline/orchestrator.py`. The `deps` object isolates all Flow/LLM I/O so the orchestrator's control flow is what's tested; production uses `DefaultDeps`.

```python
"""Video-pipeline orchestrator: idempotent, resume-safe, concurrency-capped.

run(short_id) walks product -> video -> scene, advancing DB status through the
guarded transitions and producing composites/storyboards/clips. All external
I/O is funneled through a `deps` object (DefaultDeps in production) so tests
inject deterministic fakes. Merge step is added in Phase 5.
"""
from __future__ import annotations

import asyncio
from typing import Any, Optional

from sqlmodel import select

from flowboard.db.session import get_session
from flowboard.db.video_pipeline_models import (
    VideoPipelineRun, VideoPipelineProduct, VideoPipelineVideo, VideoPipelineScene,
)
from flowboard.services.video_pipeline import transitions as tr
from flowboard.services.video_pipeline import storage
from flowboard.services.video_pipeline.clip_gen import ClipGenError
from flowboard.services.video_pipeline.storyboard_gen import StoryboardGenError


class DefaultDeps:
    """Production generation deps — delegate to the real services."""

    async def ensure_project(self, run: VideoPipelineRun) -> str:
        from flowboard.services.flow_sdk import get_flow_sdk
        if run.flow_project_id:
            return run.flow_project_id
        resp = await get_flow_sdk().create_project(f"VideoPipeline {run.short_id}")
        pid = resp.get("project_id")
        if not pid:
            raise RuntimeError(resp.get("error") or "create_project failed")
        with get_session() as s:
            r = s.get(VideoPipelineRun, run.id)
            r.flow_project_id = pid
            s.add(r)
            s.commit()
        return pid

    async def gen_composites(self, **k):
        from flowboard.services.video_pipeline.composite_gen import generate_composites
        return await generate_composites(**k)

    async def plan_script(self, *, script_brief, scene_count):
        from flowboard.services.video_pipeline.script_planner import plan_script
        return await plan_script(script_brief=script_brief, scene_count=scene_count)

    async def gen_storyboard(self, **k):
        from flowboard.services.video_pipeline.storyboard_gen import generate_storyboard
        # drop indexing kwargs the real fn doesn't accept
        k.pop("product_index", None); k.pop("video_index", None); k.pop("scene_index", None)
        return await generate_storyboard(**k)

    async def gen_clip(self, *, product_index, video_index, scene_index, **k):
        from flowboard.services.video_pipeline.clip_gen import generate_clip
        return await generate_clip(**k)


def _is_cancelled(short_id: str) -> bool:
    with get_session() as s:
        run = s.exec(select(VideoPipelineRun).where(
            VideoPipelineRun.short_id == short_id)).first()
        return bool(run and run.cancelled)


async def run(short_id: str, *, deps: Optional[Any] = None) -> None:
    deps = deps or DefaultDeps()
    storage.ensure_run_dirs(short_id)

    with get_session() as s:
        run_row = s.exec(select(VideoPipelineRun).where(
            VideoPipelineRun.short_id == short_id)).first()
        if run_row is None:
            return
        inputs = dict(run_row.inputs)
        run_obj_id = run_row.id
        already_cancelled = run_row.cancelled

    if already_cancelled:
        tr.set_run_status(short_id, "cancelled", force=True)
        return

    # resolving -> generating
    tr.set_run_status(short_id, "resolving", force=True)
    project_id = await deps.ensure_project(_reload_run(run_obj_id))
    tr.set_run_status(short_id, "generating", force=True)

    aspect = inputs.get("aspect_ratio", "9:16")
    quality = inputs.get("quality", "standard")
    cap = int(inputs.get("concurrency_cap", 4))
    sem = asyncio.Semaphore(cap)
    character_mid = inputs["character"]["media_id"]
    background_mid = inputs["background"]["media_id"]
    script_brief = inputs.get("script_brief", "")

    with get_session() as s:
        products = sorted(s.exec(select(VideoPipelineProduct).where(
            VideoPipelineProduct.run_id == run_obj_id)).all(), key=lambda p: p.product_index)
        products = [(p.product_index, p.media_id) for p in products]

    for product_index, product_mid in products:
        if _is_cancelled(short_id):
            tr.set_run_status(short_id, "cancelled", force=True)
            return
        await _run_product(short_id, run_obj_id, deps, project_id, product_index,
                           product_mid, character_mid, background_mid, script_brief,
                           aspect, quality, sem)

    if _is_cancelled(short_id):
        tr.set_run_status(short_id, "cancelled", force=True)
        return
    # Phase 5 will transition to "merging" then "done"; for now leave generating.


def _reload_run(run_id: int) -> VideoPipelineRun:
    with get_session() as s:
        return s.get(VideoPipelineRun, run_id)


async def _run_product(short_id, run_id, deps, project_id, product_index, product_mid,
                       character_mid, background_mid, script_brief, aspect, quality, sem):
    with get_session() as s:
        videos = sorted(s.exec(select(VideoPipelineVideo).where(
            (VideoPipelineVideo.run_id == run_id) &
            (VideoPipelineVideo.product_index == product_index)).all() if False else
            s.exec(select(VideoPipelineVideo).where(
                VideoPipelineVideo.run_id == run_id,
                VideoPipelineVideo.product_index == product_index)).all()),
            key=lambda v: v.video_index)
        video_rows = [(v.id, v.video_index, v.composite_media_id, v.status) for v in videos]

    n = len(video_rows)
    # Composites: generate once per product, assign one variant per video (skip done).
    need_composite = [v for v in video_rows if not v[2]]
    if need_composite:
        composites = await deps.gen_composites(
            character_media_id=character_mid, product_media_id=product_mid,
            project_id=project_id, aspect_ratio=aspect, variant_count=n,
            script_brief=script_brief)
        with get_session() as s:
            for (vid_id, vidx, comp_mid, _status), entry in zip(video_rows, composites):
                v = s.get(VideoPipelineVideo, vid_id)
                if not v.composite_media_id:
                    v.composite_media_id = entry["media_id"]
                    s.add(v)
            s.commit()
        for vid_id, vidx, _comp, _status in video_rows:
            with get_session() as s:
                v = s.get(VideoPipelineVideo, vid_id)
                if v.status == "pending":
                    pass
            tr.set_video_status(short_id, vid_id, "composite_done")

    async def run_one_video(vid_id, vidx):
        async with sem:
            if _is_cancelled(short_id):
                return
            await _run_video(short_id, run_id, deps, project_id, product_index, vidx,
                             vid_id, background_mid, script_brief, aspect, quality)

    await asyncio.gather(*[run_one_video(vid_id, vidx)
                           for vid_id, vidx, _c, _s in video_rows])


async def _run_video(short_id, run_id, deps, project_id, product_index, video_index,
                     video_id, background_mid, script_brief, aspect, quality):
    with get_session() as s:
        v = s.get(VideoPipelineVideo, video_id)
        composite_mid = v.composite_media_id
        video_status = v.status
        scenes = sorted(s.exec(select(VideoPipelineScene).where(
            VideoPipelineScene.run_id == run_id,
            VideoPipelineScene.product_index == product_index,
            VideoPipelineScene.video_index == video_index)).all(),
            key=lambda sc: sc.scene_index)
        scene_rows = [(sc.id, sc.scene_index, sc.status, sc.image_prompt,
                       sc.video_prompt, sc.storyboard_media_id) for sc in scenes]

    # Script: only if scenes lack prompts (resume-safe).
    if any(not ip for (_id, _idx, _st, ip, _vp, _sb) in scene_rows):
        script = await deps.plan_script(script_brief=script_brief, scene_count=len(scene_rows))
        with get_session() as s:
            for (sid, sidx, _st, _ip, _vp, _sb), sc_def in zip(scene_rows, script):
                sc = s.get(VideoPipelineScene, sid)
                if not sc.image_prompt:
                    sc.image_prompt = sc_def["image_prompt"]
                    sc.video_prompt = sc_def["video_prompt"]
                    s.add(sc)
            s.commit()
        if video_status in ("composite_done",):
            tr.set_video_status(short_id, video_id, "scripted")
        # refresh scene rows with prompts
        with get_session() as s:
            scenes = sorted(s.exec(select(VideoPipelineScene).where(
                VideoPipelineScene.run_id == run_id,
                VideoPipelineScene.product_index == product_index,
                VideoPipelineScene.video_index == video_index)).all(),
                key=lambda sc: sc.scene_index)
            scene_rows = [(sc.id, sc.scene_index, sc.status, sc.image_prompt,
                           sc.video_prompt, sc.storyboard_media_id) for sc in scenes]
    elif video_status == "composite_done":
        tr.set_video_status(short_id, video_id, "scripted")

    for sid, sidx, status, image_prompt, video_prompt, sb_mid in scene_rows:
        if _is_cancelled(short_id):
            return
        if status in ("clip_done", "merged"):
            continue
        try:
            # storyboard
            if status in ("pending", "storyboard_running") or not sb_mid:
                tr.set_scene_status(short_id, sid, "storyboard_running")
                sb = await deps.gen_storyboard(
                    image_prompt=image_prompt, composite_media_id=composite_mid,
                    background_media_id=background_mid, project_id=project_id,
                    aspect_ratio=aspect,
                    product_index=product_index, video_index=video_index, scene_index=sidx)
                with get_session() as s:
                    sc = s.get(VideoPipelineScene, sid)
                    sc.storyboard_media_id = sb
                    s.add(sc); s.commit()
                tr.set_scene_status(short_id, sid, "storyboard_done")
            else:
                sb = sb_mid
            # clip
            tr.set_scene_status(short_id, sid, "clip_running")
            clip = await deps.gen_clip(
                video_prompt=video_prompt, start_media_id=sb, project_id=project_id,
                aspect_ratio=aspect, quality=quality,
                product_index=product_index, video_index=video_index, scene_index=sidx)
            with get_session() as s:
                sc = s.get(VideoPipelineScene, sid)
                sc.clip_media_id = clip
                s.add(sc); s.commit()
            tr.set_scene_status(short_id, sid, "clip_done")
        except (StoryboardGenError, ClipGenError) as e:
            tr.set_scene_status(short_id, sid, "failed", error=str(e))

    # video -> scenes_done if every scene reached a terminal positive state
    with get_session() as s:
        scenes = s.exec(select(VideoPipelineScene).where(
            VideoPipelineScene.run_id == run_id,
            VideoPipelineScene.product_index == product_index,
            VideoPipelineScene.video_index == video_index)).all()
        v = s.get(VideoPipelineVideo, video_id)
        cur = v.status
    if all(sc.status in ("clip_done", "merged", "failed") for sc in scenes) and cur == "scripted":
        tr.set_video_status(short_id, video_id, "scenes_done")
```

> This is the most complex unit. Implement it incrementally against the test file, running `pytest tests/test_video_pipeline_orchestrator.py -q` after each sub-behavior (happy path → per-scene failure → resume → cancel). The `_run_product` query is written defensively; simplify the `select(...).where(...)` to the standard SQLModel multi-condition form once it's green. Keep all I/O behind `deps`.

Run: `cd agent && python -m pytest tests/test_video_pipeline_orchestrator.py -q`. Expect pass.

- [ ] **Step 3: Commit**

```bash
git add agent/flowboard/services/video_pipeline/orchestrator.py agent/tests/test_video_pipeline_orchestrator.py
git commit -m "feat(video-pipeline): orchestrator (idempotent, resume-safe, concurrency-capped)"
```

---

### Task 4.5: Wire the real orchestrator into `POST /runs/{sid}/start`

Replace the Phase 2 stub with a real background-task launch following the `routes/plans.py` pattern.

**Files:**
- Modify: `agent/flowboard/routes/video_pipeline.py`
- Create: `agent/tests/test_video_pipeline_start_task.py`

- [ ] **Step 1: Write the failing test**

Write to `agent/tests/test_video_pipeline_start_task.py`:

```python
import pytest

from flowboard.routes import video_pipeline as vp_routes


def _payload():
    return {"type_key": "product_review", "inputs": {
        "character": {"source": "upload", "media_id": "c"},
        "background": {"source": "upload", "media_id": "b"},
        "products": [{"source": "upload", "media_id": "p0"}],
        "script_brief": "x", "aspect_ratio": "9:16",
        "video_count": 1, "scene_count": 1}}


def test_start_launches_orchestrator(client, monkeypatch):
    launched = {}

    async def fake_orchestrator_run(short_id, **k):
        launched["short_id"] = short_id

    monkeypatch.setattr(vp_routes, "_orchestrator_run", fake_orchestrator_run)

    sid = client.post("/api/video-pipeline/runs", json=_payload()).json()["short_id"]
    r = client.post(f"/api/video-pipeline/runs/{sid}/start")
    assert r.status_code == 202

    # allow the scheduled task to run
    import asyncio, time
    for _ in range(50):
        if launched.get("short_id") == sid:
            break
        time.sleep(0.02)
    assert launched.get("short_id") == sid
```

> `TestClient` runs the app in its own event loop; a `create_task` scheduled inside the request handler executes when the loop ticks. The poll loop above gives it time. If the test proves flaky under `TestClient`, instead unit-test the launch helper directly (call `start_run`'s task-launch function with a fake loop) — but prefer the integration form first.

- [ ] **Step 2: Replace the start handler**

In `agent/flowboard/routes/video_pipeline.py`, add near the top:

```python
import asyncio
import logging
from flowboard.services.video_pipeline import orchestrator as _vp_orchestrator

logger = logging.getLogger(__name__)
_active_vp_tasks: dict[str, asyncio.Task] = {}

# indirection point so tests can monkeypatch the coroutine fn
_orchestrator_run = _vp_orchestrator.run
```

Replace the `start_run` body:

```python
@router.post("/runs/{short_id}/start", status_code=202)
def start_run(short_id: str):
    with get_session() as s:
        run = s.exec(select(VideoPipelineRun).where(
            VideoPipelineRun.short_id == short_id)).first()
        if run is None:
            raise HTTPException(status_code=404, detail="run not found")

    task = asyncio.create_task(_orchestrator_run(short_id), name=f"vp-run-{short_id}")
    _active_vp_tasks[short_id] = task

    def _cleanup(t: asyncio.Task) -> None:
        _active_vp_tasks.pop(short_id, None)
        exc = t.exception() if not t.cancelled() else None
        if exc is not None:
            logger.exception("video-pipeline run %s crashed", short_id, exc_info=exc)
            try:
                from flowboard.services.video_pipeline import transitions as tr
                tr.set_run_status(short_id, "failed", error=str(exc), force=True)
            except Exception:  # noqa: BLE001
                pass

    task.add_done_callback(_cleanup)
    return Response(status_code=202)
```

> Calling `_orchestrator_run(short_id)` (the module attribute) is what makes the monkeypatch in the test effective. Verify the canvas pipeline's `routes/plans.py` uses the same `add_done_callback` cleanup shape and mirror it.

Run: `cd agent && python -m pytest tests/test_video_pipeline_start_task.py -q` and the full suite.

- [ ] **Step 3: Commit**

```bash
git add agent/flowboard/routes/video_pipeline.py agent/tests/test_video_pipeline_start_task.py
git commit -m "feat(video-pipeline): launch orchestrator as background task on start"
```

---

### Task 4.6: Frontend run store (polling) + progress page

**Files:**
- Create: `frontend/src/video-pipeline/runStore.ts` (polling store, mirrors `src/store/pipeline.ts`)
- Modify: `frontend/src/video-pipeline/pages/PipelineRunDetailPage.tsx` (replace placeholder)
- Modify: `frontend/src/styles.css` (progress styles)

> Component/store tests in Phase 7. Verify via lint + manual against a live backend.

- [ ] **Step 1: Implement the polling run store**

Write to `frontend/src/video-pipeline/runStore.ts`, mirroring the recursive-`setTimeout` pattern in `src/store/pipeline.ts`:

```typescript
import { create } from "zustand";
import { vpGetRun, type VPRunDTO } from "../api/client";

const POLL_MS = 1500;
const TERMINAL = new Set(["done", "failed", "cancelled"]);

interface RunStoreState {
  run: VPRunDTO | null;
  error: string | null;
  pollTimer: ReturnType<typeof setTimeout> | null;
  start: (shortId: string) => void;
  stop: () => void;
  refreshOnce: (shortId: string) => Promise<void>;
}

export const useRunStore = create<RunStoreState>((set, get) => ({
  run: null,
  error: null,
  pollTimer: null,

  refreshOnce: async (shortId) => {
    try {
      const run = await vpGetRun(shortId);
      set({ run, error: null });
    } catch (e) {
      set({ error: e instanceof Error ? e.message : "poll failed" });
    }
  },

  start: (shortId) => {
    get().stop();
    const tick = async () => {
      await get().refreshOnce(shortId);
      const status = get().run?.status;
      if (status && TERMINAL.has(status)) {
        set({ pollTimer: null });
        return;
      }
      set({ pollTimer: setTimeout(tick, POLL_MS) });
    };
    void tick();
  },

  stop: () => {
    const t = get().pollTimer;
    if (t) clearTimeout(t);
    set({ pollTimer: null });
  },
}));
```

- [ ] **Step 2: Implement the progress page**

Replace `frontend/src/video-pipeline/pages/PipelineRunDetailPage.tsx`. Subscribe to the run store on mount (start polling), stop on unmount. Render: run header (short_id, status badge, total progress bar `clips_done/clips_total`), then products → video cards → scene cards. Each scene card shows the storyboard thumbnail (`/media/{storyboard_media_id}`), clip status, and `image_prompt` + `video_prompt` (read-only for now; inline edit lands in Phase 6). Each video card shows the composite thumbnail.

```tsx
import { useEffect } from "react";
import { useParams } from "react-router-dom";
import { useRunStore } from "../runStore";

export function PipelineRunDetailPage() {
  const { shortId } = useParams<{ shortId: string }>();
  const run = useRunStore((s) => s.run);
  const error = useRunStore((s) => s.error);
  const start = useRunStore((s) => s.start);
  const stop = useRunStore((s) => s.stop);

  useEffect(() => {
    if (!shortId) return;
    start(shortId);
    return () => stop();
  }, [shortId, start, stop]);

  if (error && !run) return <div className="vp-page" role="alert">Lỗi: {error}</div>;
  if (!run) return <div className="vp-page">Đang tải…</div>;

  const { clips_done, clips_total } = run.progress;
  const pct = clips_total ? Math.round((clips_done / clips_total) * 100) : 0;

  return (
    <div className="vp-page vp-run" data-testid="vp-run-detail-page">
      <header className="vp-run__header">
        <h1>Run {run.short_id}</h1>
        <span className={`vp-run__badge vp-run__badge--${run.status}`}>{run.status}</span>
        <div className="vp-run__progress">
          <div className="vp-run__progress-bar" style={{ width: `${pct}%` }} />
          <span>{clips_done}/{clips_total} clip · {pct}%</span>
        </div>
      </header>

      {run.products.map((p) => (
        <section key={p.id} className="vp-run__product">
          <h2>Sản phẩm {p.product_index + 1}</h2>
          {p.videos.map((v) => (
            <div key={v.id} className="vp-video-card" data-testid={`video-${v.id}`}>
              <div className="vp-video-card__composite">
                {v.composite_media_id && <img src={`/media/${v.composite_media_id}`} alt="composite" />}
                <span className={`vp-video-card__status vp-video-card__status--${v.status}`}>{v.status}</span>
              </div>
              <div className="vp-video-card__scenes">
                {v.scenes.map((sc) => (
                  <div key={sc.id} className={`vp-scene-card vp-scene-card--${sc.status}`} data-testid={`scene-${sc.id}`}>
                    {sc.storyboard_media_id && <img src={`/media/${sc.storyboard_media_id}`} alt="storyboard" />}
                    <div className="vp-scene-card__status">{sc.status}</div>
                    <div className="vp-scene-card__prompts">
                      <p>{sc.image_prompt}</p>
                      <p>{sc.video_prompt}</p>
                    </div>
                    {sc.error && <div className="vp-scene-card__error">{sc.error}</div>}
                  </div>
                ))}
              </div>
              {v.merged_url && (
                <video className="vp-video-card__merged" src={v.merged_url} controls />
              )}
            </div>
          ))}
        </section>
      ))}
    </div>
  );
}
```

- [ ] **Step 3: Progress styles + manual verify + commit**

Add `.vp-run*`, `.vp-video-card*`, `.vp-scene-card*` styles (status colors from `--success`/`--warn`/`--error`/`--accent`). Then:

```bash
cd frontend && npm run lint
```
Manual (full stack running, real Flow creds): create a run from the wizard → land on progress page → watch statuses advance pending → storyboard → clip as polling refreshes.

```bash
git add frontend/src/video-pipeline/runStore.ts frontend/src/video-pipeline/pages/PipelineRunDetailPage.tsx frontend/src/styles.css
git commit -m "feat(video-pipeline): polling run store + live progress page"
```

---

## Phase 5 — Merger (ffmpeg) + merge step + download / preview / zip

**Outcome:** When a video's scenes are all done, the orchestrator merges the clips into a single `.mp4` (`merged/p{i}-v{k}.mp4`), the video reaches `done`, and the run reaches `done`. Users can preview inline, download a single video, or download all as a `.zip`. ffmpeg comes from `imageio-ffmpeg` (portable, no PATH dependency).

### Task 5.1: Add `imageio-ffmpeg` dependency

**Files:**
- Modify: `agent/requirements.txt` (or `pyproject.toml` — match the project's dependency file)

- [ ] **Step 1: Add the dependency**

Add `imageio-ffmpeg>=0.5.1` to the backend dependency list. Install:
```bash
cd agent && pip install "imageio-ffmpeg>=0.5.1"
```
Verify the binary resolves:
```bash
python -c "import imageio_ffmpeg; print(imageio_ffmpeg.get_ffmpeg_exe())"
```
Expect a path to a bundled `ffmpeg` executable.

- [ ] **Step 2: Commit**

```bash
git add agent/requirements.txt
git commit -m "build(video-pipeline): add imageio-ffmpeg for portable ffmpeg"
```

---

### Task 5.2: `merger` (concat + crossfade), atomic write

Two code paths: `crossfade_sec == 0` → concat demuxer (no re-encode, instant); `crossfade_sec > 0` → `filter_complex` pairwise `xfade` (+ `acrossfade` if audio). Writes `*.tmp` then `os.replace` (atomic). The ffmpeg command builder is a **pure function** (tested without running ffmpeg); the runner is mocked in unit tests and exercised for real in manual QA.

**Files:**
- Create: `agent/flowboard/services/video_pipeline/merger.py`
- Create: `agent/tests/test_video_pipeline_merger.py`

- [ ] **Step 1: Write the failing test**

Write to `agent/tests/test_video_pipeline_merger.py`:

```python
from pathlib import Path

import pytest

from flowboard.services.video_pipeline import merger


def test_build_concat_command_no_crossfade(tmp_path):
    clips = [tmp_path / "a.mp4", tmp_path / "b.mp4"]
    out = tmp_path / "out.mp4"
    cmd, listfile = merger.build_concat_command("ffmpeg", clips, out)
    assert cmd[0] == "ffmpeg"
    assert "-f" in cmd and "concat" in cmd
    assert str(out) in cmd
    assert listfile is not None and listfile.exists()
    content = listfile.read_text()
    assert "a.mp4" in content and "b.mp4" in content


def test_build_xfade_command_with_audio(tmp_path):
    clips = [tmp_path / "a.mp4", tmp_path / "b.mp4", tmp_path / "c.mp4"]
    out = tmp_path / "out.mp4"
    cmd = merger.build_xfade_command("ffmpeg", clips, out,
                                     crossfade_sec=0.4, durations=[2.0, 2.0, 2.0],
                                     audio=True)
    joined = " ".join(cmd)
    assert "xfade" in joined
    assert "acrossfade" in joined
    assert str(out) in cmd


def test_build_xfade_single_clip_is_copy(tmp_path):
    clips = [tmp_path / "only.mp4"]
    out = tmp_path / "out.mp4"
    cmd = merger.build_xfade_command("ffmpeg", clips, out, crossfade_sec=0.4,
                                     durations=[2.0], audio=True)
    # one clip: nothing to crossfade -> straight copy
    assert "-c" in cmd and "copy" in cmd


@pytest.mark.asyncio
async def test_merge_writes_atomically(tmp_path, monkeypatch):
    clips = [tmp_path / "a.mp4", tmp_path / "b.mp4"]
    for c in clips:
        c.write_bytes(b"\x00\x00")
    out = tmp_path / "merged.mp4"

    ran = {}
    async def fake_run(cmd):
        # simulate ffmpeg writing the *.tmp target (last cmd arg)
        Path(cmd[-1]).write_bytes(b"MERGED")
        ran["cmd"] = cmd
        return 0

    res = await merger.merge_clips(
        clips=clips, out_path=out, crossfade_sec=0.0, audio=True,
        ffmpeg_exe="ffmpeg", runner=fake_run)
    assert out.exists()
    assert out.read_bytes() == b"MERGED"
    assert res["file_size_bytes"] == 6
    # tmp cleaned
    assert not list(tmp_path.glob("*.tmp"))


@pytest.mark.asyncio
async def test_merge_nonzero_exit_raises(tmp_path):
    clips = [tmp_path / "a.mp4"]
    clips[0].write_bytes(b"x")
    out = tmp_path / "m.mp4"

    async def fail_run(cmd):
        return 1

    with pytest.raises(merger.MergeError):
        await merger.merge_clips(clips=clips, out_path=out, crossfade_sec=0.0,
                                 audio=True, ffmpeg_exe="ffmpeg", runner=fail_run)
```

- [ ] **Step 2: Implement merger**

Write to `agent/flowboard/services/video_pipeline/merger.py`:

```python
"""Merge per-scene clips into one mp4 via portable ffmpeg.

- crossfade_sec == 0 : concat demuxer, stream copy (instant, no re-encode).
- crossfade_sec  > 0 : filter_complex pairwise xfade (+ acrossfade for audio).
Atomic: write *.tmp then os.replace. Command builders are pure; the runner is
injected so unit tests never spawn ffmpeg.
"""
from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path
from typing import Awaitable, Callable, Optional


class MergeError(Exception):
    pass


def get_ffmpeg_exe() -> str:
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def build_concat_command(ffmpeg_exe: str, clips: list[Path], out_path: Path):
    """Concat demuxer, stream copy. Returns (cmd, listfile_path)."""
    listfile = out_path.parent / f".concat-{out_path.stem}.txt"
    listfile.write_text("".join(f"file '{c.as_posix()}'\n" for c in clips), encoding="utf-8")
    cmd = [ffmpeg_exe, "-y", "-f", "concat", "-safe", "0",
           "-i", str(listfile), "-c", "copy", str(out_path)]
    return cmd, listfile


def build_xfade_command(ffmpeg_exe: str, clips: list[Path], out_path: Path, *,
                        crossfade_sec: float, durations: list[float], audio: bool):
    if len(clips) == 1:
        return [ffmpeg_exe, "-y", "-i", str(clips[0]), "-c", "copy", str(out_path)]

    cmd = [ffmpeg_exe, "-y"]
    for c in clips:
        cmd += ["-i", str(c)]

    filters = []
    # video xfade chain
    prev = "[0:v]"
    offset = 0.0
    for i in range(1, len(clips)):
        offset += durations[i - 1] - crossfade_sec
        out_label = f"[vx{i}]"
        filters.append(
            f"{prev}[{i}:v]xfade=transition=fade:duration={crossfade_sec}:"
            f"offset={offset:.3f}{out_label}")
        prev = out_label
    video_out = prev

    map_args = ["-map", video_out]
    if audio:
        aprev = "[0:a]"
        for i in range(1, len(clips)):
            out_label = f"[ax{i}]"
            filters.append(f"{aprev}[{i}:a]acrossfade=d={crossfade_sec}{out_label}")
            aprev = out_label
        map_args += ["-map", aprev]

    cmd += ["-filter_complex", ";".join(filters)] + map_args + [str(out_path)]
    return cmd


async def _default_runner(cmd: list[str]) -> int:
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    _out, err = await proc.communicate()
    if proc.returncode != 0:
        raise MergeError(err.decode(errors="replace")[-2000:])
    return proc.returncode


async def merge_clips(
    *,
    clips: list[Path],
    out_path: Path,
    crossfade_sec: float,
    audio: bool,
    durations: Optional[list[float]] = None,
    ffmpeg_exe: Optional[str] = None,
    runner: Optional[Callable[[list[str]], Awaitable[int]]] = None,
) -> dict:
    if not clips:
        raise MergeError("no clips to merge")
    ffmpeg_exe = ffmpeg_exe or get_ffmpeg_exe()
    runner = runner or _default_runner
    out_path.parent.mkdir(parents=True, exist_ok=True)

    fd, tmp = tempfile.mkstemp(dir=str(out_path.parent), suffix=".tmp")
    os.close(fd)
    tmp_path = Path(tmp)
    listfile: Optional[Path] = None
    try:
        if crossfade_sec and crossfade_sec > 0:
            durations = durations or [2.0] * len(clips)
            cmd = build_xfade_command(ffmpeg_exe, clips, tmp_path,
                                      crossfade_sec=crossfade_sec,
                                      durations=durations, audio=audio)
        else:
            cmd, listfile = build_concat_command(ffmpeg_exe, clips, tmp_path)

        rc = await runner(cmd)
        if rc != 0:
            raise MergeError(f"ffmpeg exited {rc}")
        if not tmp_path.exists() or tmp_path.stat().st_size == 0:
            raise MergeError("ffmpeg produced no output")
        os.replace(tmp_path, out_path)
        size = out_path.stat().st_size
        return {"file_size_bytes": size, "path": str(out_path)}
    finally:
        if tmp_path.exists():
            try: tmp_path.unlink()
            except OSError: pass
        if listfile and listfile.exists():
            try: listfile.unlink()
            except OSError: pass
```

Run: `cd agent && python -m pytest tests/test_video_pipeline_merger.py -q`. Expect pass.

> The `xfade offset` math assumes known per-clip durations. Veo clips are short fixed-length (e.g. ~ a few seconds). If real durations are needed, probe with `ffprobe` (bundled alongside `imageio-ffmpeg`'s ffmpeg, or via `-i` parse) in a follow-up; for v1 the default `[2.0]*n` is acceptable for concat (durations unused) and a reasonable estimate for xfade. Validate visually in manual QA (Phase 7) and adjust the default if clips differ.

- [ ] **Step 3: Commit**

```bash
git add agent/flowboard/services/video_pipeline/merger.py agent/tests/test_video_pipeline_merger.py agent/requirements.txt
git commit -m "feat(video-pipeline): ffmpeg merger (concat + xfade, atomic write)"
```

---

### Task 5.3: Clip download helper + merge step in orchestrator

The merger needs local clip files. Add a helper that ensures a clip `media_id` is cached locally (reuse `media_service.cached_path` / `fetch_and_cache`), copy/symlink into the run's `clips/` dir with the canonical name, then extend the orchestrator: after a video reaches `scenes_done`, merge its `clip_done` scenes → set `merged_local_path`, `merged_url`, `duration_sec`, `file_size_bytes`, video `done`; after all videos resolve, run `done`.

**Files:**
- Modify: `agent/flowboard/services/video_pipeline/orchestrator.py`
- Create: `agent/flowboard/services/video_pipeline/clip_fetch.py`
- Create: `agent/tests/test_video_pipeline_merge_step.py`

- [ ] **Step 1: Write the failing test**

Write to `agent/tests/test_video_pipeline_merge_step.py`:

```python
import pytest
from pathlib import Path
from sqlmodel import select

from flowboard.db.session import get_session
from flowboard.db.video_pipeline_models import VideoPipelineRun, VideoPipelineVideo
from flowboard.services.video_pipeline import run_builder, orchestrator, storage


class MergeFakeDeps:
    async def ensure_project(self, run): return "proj"
    async def gen_composites(self, **k):
        return [{"media_id": f"comp{i}", "url": "u"} for i in range(k["variant_count"])]
    async def plan_script(self, *, script_brief, scene_count):
        return [{"image_prompt": f"ip{j}", "video_prompt": f"vp{j}"} for j in range(scene_count)]
    async def gen_storyboard(self, **k): return f"sb-{k['scene_index']}"
    async def gen_clip(self, *, product_index, video_index, scene_index, **k):
        return f"clip-{scene_index}"
    async def fetch_clip_to(self, media_id, dest: Path):
        dest.write_bytes(b"CLIP"); return dest
    async def merge(self, *, clips, out_path, crossfade_sec, audio, durations=None):
        out_path.write_bytes(b"MERGED")
        return {"file_size_bytes": out_path.stat().st_size, "path": str(out_path)}


@pytest.mark.asyncio
async def test_merge_step_completes_run(monkeypatch, tmp_path):
    monkeypatch.setattr(storage, "STORAGE_DIR", tmp_path)
    run = run_builder.create_run(type_key="product_review", inputs={
        "character": {"source": "upload", "media_id": "c"},
        "background": {"source": "upload", "media_id": "b"},
        "products": [{"source": "upload", "media_id": "p0"}],
        "script_brief": "x", "aspect_ratio": "9:16",
        "video_count": 1, "scene_count": 2, "crossfade_sec": 0.0})
    await orchestrator.run(run.short_id, deps=MergeFakeDeps())

    with get_session() as s:
        v = s.exec(select(VideoPipelineVideo).where(
            VideoPipelineVideo.run_id == run.id)).first()
        run_row = s.get(VideoPipelineRun, run.id)
    assert v.status == "done"
    assert v.merged_local_path and Path(v.merged_local_path).exists()
    assert v.merged_url
    assert run_row.status == "done"
```

- [ ] **Step 2: Implement clip_fetch + extend orchestrator deps and merge flow**

Write to `agent/flowboard/services/video_pipeline/clip_fetch.py`:

```python
"""Ensure a clip media_id exists as a local file at a destination path."""
from __future__ import annotations

import shutil
from pathlib import Path

from flowboard.services import media as media_service


async def fetch_clip_to(media_id: str, dest: Path) -> Path:
    src = media_service.cached_path(media_id)
    if src is None:
        # not cached yet -> trigger fetch_and_cache then re-resolve
        await media_service.fetch_and_cache(media_id)
        src = media_service.cached_path(media_id)
    if src is None:
        raise FileNotFoundError(f"clip {media_id} not available locally")
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dest)
    return dest
```

> Confirm `media_service.fetch_and_cache` is awaitable and that `cached_path` resolves after it. If `fetch_and_cache` is sync, drop the `await`. Match `services/media.py`.

In `orchestrator.py`, add to `DefaultDeps`:

```python
    async def fetch_clip_to(self, media_id, dest):
        from flowboard.services.video_pipeline.clip_fetch import fetch_clip_to
        return await fetch_clip_to(media_id, dest)

    async def merge(self, *, clips, out_path, crossfade_sec, audio, durations=None):
        from flowboard.services.video_pipeline.merger import merge_clips
        return await merge_clips(clips=clips, out_path=out_path,
                                 crossfade_sec=crossfade_sec, audio=audio,
                                 durations=durations)
```

Add a `_merge_video` function and call it from `_run_video` once the video is `scenes_done` (and skip if already `done`). Then, at the end of `run(...)`, after all products, if every video is terminal, set run `done`:

```python
async def _merge_video(short_id, run_id, deps, video_id, product_index, video_index,
                       crossfade_sec, audio):
    from flowboard.services.video_pipeline import storage
    with get_session() as s:
        v = s.get(VideoPipelineVideo, video_id)
        if v.status == "done":
            return
        scenes = sorted(s.exec(select(VideoPipelineScene).where(
            VideoPipelineScene.run_id == run_id,
            VideoPipelineScene.product_index == product_index,
            VideoPipelineScene.video_index == video_index)).all(),
            key=lambda sc: sc.scene_index)
        clip_ids = [sc.clip_media_id for sc in scenes if sc.status == "clip_done" and sc.clip_media_id]
        run = s.get(VideoPipelineRun, run_id)
        short = run.short_id
    if not clip_ids:
        tr.set_video_status(short_id, video_id, "failed", error="no clips to merge")
        return

    tr.set_video_status(short_id, video_id, "merging")
    clips_dir = storage.run_dir(short).joinpath("clips")
    local_clips = []
    for j, mid in enumerate(clip_ids):
        dest = storage.clip_path(short, product_index, video_index, j)
        local_clips.append(await deps.fetch_clip_to(mid, dest))
    out_path = storage.merged_path(short, product_index, video_index)
    res = await deps.merge(clips=local_clips, out_path=out_path,
                           crossfade_sec=crossfade_sec, audio=audio)
    with get_session() as s:
        v = s.get(VideoPipelineVideo, video_id)
        v.merged_local_path = res["path"]
        v.merged_url = f"/api/video-pipeline/runs/{short}/videos/{video_id}/preview"
        v.file_size_bytes = res["file_size_bytes"]
        s.add(v); s.commit()
    tr.set_video_status(short_id, video_id, "done")
```

Wire `_merge_video` into `_run_video` after the `scenes_done` transition (read `crossfade_sec`/`audio_enabled` from inputs — thread them through `_run_product`/`_run_video` like `aspect`/`quality`). At the end of `run(...)`:

```python
    # finalize: if all videos terminal, run is done
    with get_session() as s:
        videos = s.exec(select(VideoPipelineVideo).where(
            VideoPipelineVideo.run_id == run_obj_id)).all()
    if videos and all(v.status in ("done", "failed") for v in videos):
        tr.set_run_status(short_id, "done", force=True)
```

> Update the Phase 4 orchestrator tests if needed: `test_happy_path_all_scenes_clip_done` asserted `run.status in ("generating","merging")` — once merge lands, the happy-path fake must also provide `fetch_clip_to`/`merge` (the Phase 4 `FakeDeps` lacks them). Either add those methods to the Phase 4 `FakeDeps` (so it still passes with merge), or relax that assertion. Prefer adding the two methods to keep both tests meaningful. Run both test files together.

Run: `cd agent && python -m pytest tests/test_video_pipeline_merge_step.py tests/test_video_pipeline_orchestrator.py -q`. Expect pass.

- [ ] **Step 3: Commit**

```bash
git add agent/flowboard/services/video_pipeline/clip_fetch.py agent/flowboard/services/video_pipeline/orchestrator.py agent/tests/test_video_pipeline_merge_step.py agent/tests/test_video_pipeline_orchestrator.py
git commit -m "feat(video-pipeline): merge step (fetch clips, ffmpeg merge, complete run)"
```

---

### Task 5.4: Preview / download / download-all routes

**Files:**
- Modify: `agent/flowboard/routes/video_pipeline.py`
- Create: `agent/tests/test_video_pipeline_download_routes.py`

- [ ] **Step 1: Write the failing test**

Write to `agent/tests/test_video_pipeline_download_routes.py`:

```python
import zipfile
import io

from sqlmodel import select

from flowboard.db.session import get_session
from flowboard.db.video_pipeline_models import VideoPipelineVideo
from flowboard.services.video_pipeline import run_builder, storage


def _run_with_merged(monkeypatch, tmp_path):
    monkeypatch.setattr(storage, "STORAGE_DIR", tmp_path)
    run = run_builder.create_run(type_key="product_review", inputs={
        "character": {"source": "upload", "media_id": "c"},
        "background": {"source": "upload", "media_id": "b"},
        "products": [{"source": "upload", "media_id": "p0"}],
        "script_brief": "x", "aspect_ratio": "9:16",
        "video_count": 1, "scene_count": 1})
    with get_session() as s:
        v = s.exec(select(VideoPipelineVideo).where(
            VideoPipelineVideo.run_id == run.id)).first()
        vid = v.id
        mp = storage.merged_path(run.short_id, 0, 0)
        mp.parent.mkdir(parents=True, exist_ok=True)
        mp.write_bytes(b"MP4DATA")
        v.merged_local_path = str(mp)
        v.status = "done"
        s.add(v); s.commit()
    return run.short_id, vid


def test_preview_streams_inline(client, monkeypatch, tmp_path):
    sid, vid = _run_with_merged(monkeypatch, tmp_path)
    r = client.get(f"/api/video-pipeline/runs/{sid}/videos/{vid}/preview")
    assert r.status_code == 200
    assert r.content == b"MP4DATA"


def test_download_is_attachment(client, monkeypatch, tmp_path):
    sid, vid = _run_with_merged(monkeypatch, tmp_path)
    r = client.get(f"/api/video-pipeline/runs/{sid}/videos/{vid}/download")
    assert r.status_code == 200
    assert "attachment" in r.headers.get("content-disposition", "")


def test_download_all_zip(client, monkeypatch, tmp_path):
    sid, vid = _run_with_merged(monkeypatch, tmp_path)
    r = client.get(f"/api/video-pipeline/runs/{sid}/download-all.zip")
    assert r.status_code == 200
    zf = zipfile.ZipFile(io.BytesIO(r.content))
    assert len(zf.namelist()) == 1


def test_preview_missing_video_404(client, monkeypatch, tmp_path):
    sid, _ = _run_with_merged(monkeypatch, tmp_path)
    r = client.get(f"/api/video-pipeline/runs/{sid}/videos/99999/preview")
    assert r.status_code == 404
```

- [ ] **Step 2: Implement the routes**

Add to `agent/flowboard/routes/video_pipeline.py`:

```python
# --- imports ---
import io
import zipfile
from pathlib import Path
from fastapi.responses import FileResponse, StreamingResponse
from flowboard.db.video_pipeline_models import VideoPipelineVideo


def _load_video(short_id: str, video_id: int):
    with get_session() as s:
        run = s.exec(select(VideoPipelineRun).where(
            VideoPipelineRun.short_id == short_id)).first()
        if run is None:
            raise HTTPException(status_code=404, detail="run not found")
        v = s.get(VideoPipelineVideo, video_id)
        if v is None or v.run_id != run.id:
            raise HTTPException(status_code=404, detail="video not found")
        return run, v


@router.get("/runs/{short_id}/videos/{video_id}/preview")
def preview_video(short_id: str, video_id: int):
    _run, v = _load_video(short_id, video_id)
    if not v.merged_local_path or not Path(v.merged_local_path).exists():
        raise HTTPException(status_code=404, detail="merged video not ready")
    return FileResponse(v.merged_local_path, media_type="video/mp4")


@router.get("/runs/{short_id}/videos/{video_id}/download")
def download_video(short_id: str, video_id: int):
    _run, v = _load_video(short_id, video_id)
    if not v.merged_local_path or not Path(v.merged_local_path).exists():
        raise HTTPException(status_code=404, detail="merged video not ready")
    fname = f"{short_id}-p{v.product_index}-v{v.video_index}.mp4"
    return FileResponse(v.merged_local_path, media_type="video/mp4", filename=fname)


@router.get("/runs/{short_id}/download-all.zip")
def download_all(short_id: str):
    with get_session() as s:
        run = s.exec(select(VideoPipelineRun).where(
            VideoPipelineRun.short_id == short_id)).first()
        if run is None:
            raise HTTPException(status_code=404, detail="run not found")
        videos = s.exec(select(VideoPipelineVideo).where(
            VideoPipelineVideo.run_id == run.id)).all()

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as zf:
        for v in videos:
            if v.merged_local_path and Path(v.merged_local_path).exists():
                zf.write(v.merged_local_path,
                         arcname=f"p{v.product_index}-v{v.video_index}.mp4")
    buf.seek(0)
    headers = {"Content-Disposition": f'attachment; filename="{short_id}.zip"'}
    return StreamingResponse(buf, media_type="application/zip", headers=headers)
```

Run: `cd agent && python -m pytest tests/test_video_pipeline_download_routes.py -q`. Expect pass. The `merged_url` set in Task 5.3 (`.../videos/{id}/preview`) now resolves.

- [ ] **Step 3: Commit**

```bash
git add agent/flowboard/routes/video_pipeline.py agent/tests/test_video_pipeline_download_routes.py
git commit -m "feat(video-pipeline): preview/download/zip routes"
```

---

### Task 5.5: Frontend — download buttons + merged preview

**Files:**
- Modify: `frontend/src/video-pipeline/pages/PipelineRunDetailPage.tsx`
- Modify: `frontend/src/api/client.ts` (download-all URL helper)

- [ ] **Step 1: Add download actions**

In the progress page: on each `done` video card, the `<video>` preview already renders from `merged_url`; add a "⤓ Tải" link to `/api/video-pipeline/runs/{shortId}/videos/{v.id}/download`. In the run header, add "⤓ Tải tất cả .zip" linking to `/api/video-pipeline/runs/{shortId}/download-all.zip` (plain anchor with `download` attr — browser handles the attachment). Optionally add a tiny helper in `client.ts`:

```typescript
export function vpDownloadAllUrl(shortId: string) {
  return `/api/video-pipeline/runs/${shortId}/download-all.zip`;
}
export function vpVideoDownloadUrl(shortId: string, videoId: number) {
  return `/api/video-pipeline/runs/${shortId}/videos/${videoId}/download`;
}
```

- [ ] **Step 2: Lint + manual verify + commit**

```bash
cd frontend && npm run lint
```
Manual: complete a run end-to-end → merged `<video>` plays inline; single download saves an `.mp4` that opens in VLC; "Tải tất cả" saves a `.zip` containing all merged videos.

```bash
git add frontend/src/video-pipeline/pages/PipelineRunDetailPage.tsx frontend/src/api/client.ts
git commit -m "feat(video-pipeline): download buttons + merged preview"
```

> **Milestone:** At the end of Phase 5 the feature is end-to-end usable — a user can produce and download `.mp4` files. Phases 6–7 add robustness (regen/resume/cancel/error UX) and the frontend test suite.

---

## Phase 6 — Regen (cascade reset) + cancel + resume + scene-prompt edit + error UX

**Outcome:** Users can regenerate at any granularity (clip / storyboard / composite / whole video / remerge), edit scene prompts inline, cancel a running run, and resume an interrupted run from a ResumeBanner. In-flight guards return 409. The progress page exposes all of this.

### Task 6.1: Cascade-reset logic (pure, tested)

A pure module computing what to reset for each regen level (without touching the DB), plus DB-applying helpers. Keeps the cascade rules unit-testable.

**Files:**
- Create: `agent/flowboard/services/video_pipeline/regen.py`
- Create: `agent/tests/test_video_pipeline_regen.py`

- [ ] **Step 1: Write the failing test**

Write to `agent/tests/test_video_pipeline_regen.py`:

```python
import pytest
from sqlmodel import select

from flowboard.db.session import get_session
from flowboard.db.video_pipeline_models import VideoPipelineVideo, VideoPipelineScene
from flowboard.services.video_pipeline import run_builder, regen, storage


def _seed_done_video(monkeypatch, tmp_path):
    monkeypatch.setattr(storage, "STORAGE_DIR", tmp_path)
    run = run_builder.create_run(type_key="product_review", inputs={
        "character": {"source": "upload", "media_id": "c"},
        "background": {"source": "upload", "media_id": "b"},
        "products": [{"source": "upload", "media_id": "p0"}],
        "script_brief": "x", "aspect_ratio": "9:16",
        "video_count": 1, "scene_count": 2})
    with get_session() as s:
        v = s.exec(select(VideoPipelineVideo).where(
            VideoPipelineVideo.run_id == run.id)).first()
        v.status = "done"; v.composite_media_id = "comp"; v.merged_local_path = "x.mp4"
        v.merged_url = "/preview"; s.add(v)
        scenes = s.exec(select(VideoPipelineScene).where(
            VideoPipelineScene.run_id == run.id)).all()
        for sc in scenes:
            sc.status = "clip_done"; sc.storyboard_media_id = "sb"; sc.clip_media_id = "cl"
            s.add(sc)
        s.commit()
        return run, v.id, [sc.id for sc in scenes]


def test_regen_clip_keeps_storyboard(monkeypatch, tmp_path):
    run, vid, scene_ids = _seed_done_video(monkeypatch, tmp_path)
    regen.reset_for_clip(run.short_id, scene_ids[0])
    with get_session() as s:
        sc = s.get(VideoPipelineScene, scene_ids[0])
        v = s.get(VideoPipelineVideo, vid)
    assert sc.clip_media_id is None
    assert sc.storyboard_media_id == "sb"      # kept
    assert sc.status == "storyboard_done"
    assert v.merged_local_path is None          # merged invalidated
    assert v.status in ("scripted", "scenes_done")


def test_regen_storyboard_clears_clip_and_storyboard(monkeypatch, tmp_path):
    run, vid, scene_ids = _seed_done_video(monkeypatch, tmp_path)
    regen.reset_for_storyboard(run.short_id, scene_ids[0])
    with get_session() as s:
        sc = s.get(VideoPipelineScene, scene_ids[0])
    assert sc.storyboard_media_id is None
    assert sc.clip_media_id is None
    assert sc.status == "pending"


def test_regen_composite_resets_all_scenes(monkeypatch, tmp_path):
    run, vid, scene_ids = _seed_done_video(monkeypatch, tmp_path)
    regen.reset_for_composite(run.short_id, vid)
    with get_session() as s:
        v = s.get(VideoPipelineVideo, vid)
        scenes = s.exec(select(VideoPipelineScene).where(
            VideoPipelineScene.run_id == run.id)).all()
    assert v.composite_media_id is None
    assert v.status == "pending"
    assert all(sc.status == "pending" and sc.storyboard_media_id is None
               and sc.clip_media_id is None for sc in scenes)


def test_regen_blocks_when_in_flight(monkeypatch, tmp_path):
    run, vid, scene_ids = _seed_done_video(monkeypatch, tmp_path)
    with get_session() as s:
        sc = s.get(VideoPipelineScene, scene_ids[0])
        sc.status = "clip_running"; s.add(sc); s.commit()
    with pytest.raises(regen.RegenConflict):
        regen.reset_for_clip(run.short_id, scene_ids[0])
```

- [ ] **Step 2: Implement regen**

Write to `agent/flowboard/services/video_pipeline/regen.py`:

```python
"""Cascade-reset rules for regeneration. Each resets the minimal set and
invalidates the video's merged output. Refuses to reset rows that are
currently *_running (409 at the API layer)."""
from __future__ import annotations

from sqlmodel import select

from flowboard.db.session import get_session
from flowboard.db.models import _utcnow
from flowboard.db.video_pipeline_models import (
    VideoPipelineRun, VideoPipelineVideo, VideoPipelineScene,
)
from flowboard.services.video_pipeline import transitions as tr
from flowboard.services.video_pipeline import storage, serializers

_RUNNING = {"storyboard_running", "clip_running"}
_VIDEO_RUNNING = {"merging"}


class RegenConflict(Exception):
    pass


def _invalidate_merged(s, video_id: int) -> None:
    v = s.get(VideoPipelineVideo, video_id)
    if v.merged_local_path:
        try:
            storage.run_dir  # noqa  (path cleanup best-effort below)
            from pathlib import Path
            p = Path(v.merged_local_path)
            if p.exists():
                p.unlink()
        except OSError:
            pass
    v.merged_local_path = None
    v.merged_url = None
    v.file_size_bytes = None
    v.duration_sec = None
    # video drops back so the orchestrator will re-merge
    if v.status == "done":
        v.status = "scenes_done"
    s.add(v)


def _video_id_for_scene(s, scene_id: int) -> int:
    sc = s.get(VideoPipelineScene, scene_id)
    if sc is None:
        raise RegenConflict(f"scene {scene_id} not found")
    v = s.exec(select(VideoPipelineVideo).where(
        VideoPipelineVideo.run_id == sc.run_id,
        VideoPipelineVideo.product_index == sc.product_index,
        VideoPipelineVideo.video_index == sc.video_index)).first()
    return v.id


def _refresh(short_id: str) -> None:
    dto = serializers.serialize_run(short_id)
    if dto is not None:
        storage.write_manifest(short_id, dto)


def reset_for_clip(short_id: str, scene_id: int) -> None:
    with get_session() as s:
        sc = s.get(VideoPipelineScene, scene_id)
        if sc is None:
            raise RegenConflict("scene not found")
        if sc.status in _RUNNING:
            raise RegenConflict("scene is running")
        sc.clip_media_id = None
        sc.status = "storyboard_done" if sc.storyboard_media_id else "pending"
        sc.error = None
        sc.updated_at = _utcnow()
        s.add(sc)
        vid = _video_id_for_scene(s, scene_id)
        _invalidate_merged(s, vid)
        s.commit()
    _refresh(short_id)


def reset_for_storyboard(short_id: str, scene_id: int) -> None:
    with get_session() as s:
        sc = s.get(VideoPipelineScene, scene_id)
        if sc is None:
            raise RegenConflict("scene not found")
        if sc.status in _RUNNING:
            raise RegenConflict("scene is running")
        sc.storyboard_media_id = None
        sc.clip_media_id = None
        sc.status = "pending"
        sc.error = None
        sc.updated_at = _utcnow()
        s.add(sc)
        vid = _video_id_for_scene(s, scene_id)
        _invalidate_merged(s, vid)
        s.commit()
    _refresh(short_id)


def reset_for_composite(short_id: str, video_id: int) -> None:
    with get_session() as s:
        v = s.get(VideoPipelineVideo, video_id)
        if v is None:
            raise RegenConflict("video not found")
        if v.status in _VIDEO_RUNNING:
            raise RegenConflict("video is merging")
        scenes = s.exec(select(VideoPipelineScene).where(
            VideoPipelineScene.run_id == v.run_id,
            VideoPipelineScene.product_index == v.product_index,
            VideoPipelineScene.video_index == v.video_index)).all()
        if any(sc.status in _RUNNING for sc in scenes):
            raise RegenConflict("a scene is running")
        for sc in scenes:
            sc.storyboard_media_id = None
            sc.clip_media_id = None
            sc.status = "pending"
            sc.error = None
            sc.updated_at = _utcnow()
            s.add(sc)
        v.composite_media_id = None
        v.status = "pending"
        v.error = None
        v.composite_attempts = (v.composite_attempts or 0) + 1
        _invalidate_merged(s, video_id)
        v.status = "pending"   # _invalidate_merged may have set scenes_done; force pending
        s.add(v)
        s.commit()
    _refresh(short_id)


def reset_for_video(short_id: str, video_id: int) -> None:
    # full reset == composite reset (covers everything downstream)
    reset_for_composite(short_id, video_id)


def reset_for_remerge(short_id: str, video_id: int) -> None:
    with get_session() as s:
        v = s.get(VideoPipelineVideo, video_id)
        if v is None:
            raise RegenConflict("video not found")
        if v.status in _VIDEO_RUNNING:
            raise RegenConflict("video is merging")
        _invalidate_merged(s, video_id)
        # keep scenes; just drop merged so orchestrator re-merges
        v.status = "scenes_done"
        s.add(v)
        s.commit()
    _refresh(short_id)
```

> `reset_for_composite` sets video status to `pending` directly (bypassing the forward-only state machine) — this is a deliberate backward reset, so it writes the field directly rather than via `tr.set_video_status` (which would reject the regression). That's why `transitions` exposes a `force=True` path; equivalently the direct write here is acceptable since regen is an explicit user action. Keep the direct writes confined to this module.

Run: `cd agent && python -m pytest tests/test_video_pipeline_regen.py -q`. Expect pass.

- [ ] **Step 3: Commit**

```bash
git add agent/flowboard/services/video_pipeline/regen.py agent/tests/test_video_pipeline_regen.py
git commit -m "feat(video-pipeline): cascade-reset regen logic + in-flight guards"
```

---

### Task 6.2: Regen / cancel / scene-edit / resume routes

After each regen reset, the orchestrator is re-launched (idempotent — it only fills the reset rows). Cancel sets `run.cancelled` + status. Scene PATCH edits prompts (only when not running). Resume = the same `start` launch.

**Files:**
- Modify: `agent/flowboard/routes/video_pipeline.py`
- Create: `agent/tests/test_video_pipeline_regen_routes.py`

- [ ] **Step 1: Write the failing test**

Write to `agent/tests/test_video_pipeline_regen_routes.py`:

```python
from sqlmodel import select

from flowboard.db.session import get_session
from flowboard.db.video_pipeline_models import (
    VideoPipelineRun, VideoPipelineVideo, VideoPipelineScene,
)
from flowboard.services.video_pipeline import run_builder
from flowboard.routes import video_pipeline as vp_routes


def _seed(client, monkeypatch, tmp_path):
    from flowboard.services.video_pipeline import storage
    monkeypatch.setattr(storage, "STORAGE_DIR", tmp_path)
    # no-op orchestrator so regen-relaunch doesn't do real work
    async def noop(short_id, **k): return None
    monkeypatch.setattr(vp_routes, "_orchestrator_run", noop)
    run = run_builder.create_run(type_key="product_review", inputs={
        "character": {"source": "upload", "media_id": "c"},
        "background": {"source": "upload", "media_id": "b"},
        "products": [{"source": "upload", "media_id": "p0"}],
        "script_brief": "x", "aspect_ratio": "9:16",
        "video_count": 1, "scene_count": 1})
    with get_session() as s:
        v = s.exec(select(VideoPipelineVideo).where(
            VideoPipelineVideo.run_id == run.id)).first()
        sc = s.exec(select(VideoPipelineScene).where(
            VideoPipelineScene.run_id == run.id)).first()
        v.status = "done"; v.composite_media_id = "comp"; s.add(v)
        sc.status = "clip_done"; sc.storyboard_media_id = "sb"; sc.clip_media_id = "cl"
        sc.image_prompt = "ip"; sc.video_prompt = "vp"; s.add(sc)
        s.commit()
        return run.short_id, v.id, sc.id


def test_cancel_sets_cancelled(client, monkeypatch, tmp_path):
    sid, vid, scid = _seed(client, monkeypatch, tmp_path)
    r = client.post(f"/api/video-pipeline/runs/{sid}/cancel")
    assert r.status_code == 200
    with get_session() as s:
        run = s.exec(select(VideoPipelineRun).where(
            VideoPipelineRun.short_id == sid)).first()
    assert run.cancelled is True


def test_patch_scene_prompt(client, monkeypatch, tmp_path):
    sid, vid, scid = _seed(client, monkeypatch, tmp_path)
    r = client.patch(f"/api/video-pipeline/runs/{sid}/scenes/{scid}",
                     json={"image_prompt": "new ip", "video_prompt": "new vp"})
    assert r.status_code == 200
    with get_session() as s:
        sc = s.get(VideoPipelineScene, scid)
    assert sc.image_prompt == "new ip"


def test_patch_scene_running_returns_409(client, monkeypatch, tmp_path):
    sid, vid, scid = _seed(client, monkeypatch, tmp_path)
    with get_session() as s:
        sc = s.get(VideoPipelineScene, scid)
        sc.status = "clip_running"; s.add(sc); s.commit()
    r = client.patch(f"/api/video-pipeline/runs/{sid}/scenes/{scid}",
                     json={"image_prompt": "x"})
    assert r.status_code == 409


def test_regen_clip_route(client, monkeypatch, tmp_path):
    sid, vid, scid = _seed(client, monkeypatch, tmp_path)
    r = client.post(f"/api/video-pipeline/runs/{sid}/scenes/{scid}/regen-clip")
    assert r.status_code == 202
    with get_session() as s:
        sc = s.get(VideoPipelineScene, scid)
    assert sc.clip_media_id is None


def test_regen_clip_running_returns_409(client, monkeypatch, tmp_path):
    sid, vid, scid = _seed(client, monkeypatch, tmp_path)
    with get_session() as s:
        sc = s.get(VideoPipelineScene, scid)
        sc.status = "clip_running"; s.add(sc); s.commit()
    r = client.post(f"/api/video-pipeline/runs/{sid}/scenes/{scid}/regen-clip")
    assert r.status_code == 409


def test_regen_composite_route(client, monkeypatch, tmp_path):
    sid, vid, scid = _seed(client, monkeypatch, tmp_path)
    r = client.post(f"/api/video-pipeline/runs/{sid}/videos/{vid}/regen-composite")
    assert r.status_code == 202
    with get_session() as s:
        v = s.get(VideoPipelineVideo, vid)
    assert v.composite_media_id is None
```

- [ ] **Step 2: Implement the routes**

Add to `agent/flowboard/routes/video_pipeline.py`:

```python
from flowboard.services.video_pipeline import regen as _regen
from flowboard.db.video_pipeline_models import VideoPipelineScene


def _relaunch(short_id: str) -> None:
    task = asyncio.create_task(_orchestrator_run(short_id), name=f"vp-regen-{short_id}")
    _active_vp_tasks[short_id] = task
    task.add_done_callback(lambda t: _active_vp_tasks.pop(short_id, None))


@router.post("/runs/{short_id}/cancel")
def cancel_run(short_id: str):
    with get_session() as s:
        run = s.exec(select(VideoPipelineRun).where(
            VideoPipelineRun.short_id == short_id)).first()
        if run is None:
            raise HTTPException(status_code=404, detail="run not found")
        run.cancelled = True
        if run.status in ("pending", "resolving", "generating", "merging"):
            run.status = "cancelled"
        s.add(run); s.commit()
    return {"cancelled": True}


class ScenePatch(BaseModel):
    image_prompt: Optional[str] = None
    video_prompt: Optional[str] = None


@router.patch("/runs/{short_id}/scenes/{scene_id}")
def patch_scene(short_id: str, scene_id: int, body: ScenePatch):
    with get_session() as s:
        sc = s.get(VideoPipelineScene, scene_id)
        if sc is None:
            raise HTTPException(status_code=404, detail="scene not found")
        if sc.status in ("storyboard_running", "clip_running"):
            raise HTTPException(status_code=409, detail="scene is running")
        if body.image_prompt is not None:
            sc.image_prompt = body.image_prompt
        if body.video_prompt is not None:
            sc.video_prompt = body.video_prompt
        s.add(sc); s.commit()
    return {"ok": True}


def _regen_guard(fn, *args):
    try:
        fn(*args)
    except _regen.RegenConflict as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.post("/runs/{short_id}/scenes/{scene_id}/regen-storyboard", status_code=202)
def regen_storyboard(short_id: str, scene_id: int):
    _regen_guard(_regen.reset_for_storyboard, short_id, scene_id)
    _relaunch(short_id)
    return Response(status_code=202)


@router.post("/runs/{short_id}/scenes/{scene_id}/regen-clip", status_code=202)
def regen_clip(short_id: str, scene_id: int):
    _regen_guard(_regen.reset_for_clip, short_id, scene_id)
    _relaunch(short_id)
    return Response(status_code=202)


@router.post("/runs/{short_id}/videos/{video_id}/regen-composite", status_code=202)
def regen_composite(short_id: str, video_id: int):
    _regen_guard(_regen.reset_for_composite, short_id, video_id)
    _relaunch(short_id)
    return Response(status_code=202)


@router.post("/runs/{short_id}/videos/{video_id}/regen-all", status_code=202)
def regen_all(short_id: str, video_id: int):
    _regen_guard(_regen.reset_for_video, short_id, video_id)
    _relaunch(short_id)
    return Response(status_code=202)


@router.post("/runs/{short_id}/videos/{video_id}/remerge", status_code=202)
def remerge(short_id: str, video_id: int):
    _regen_guard(_regen.reset_for_remerge, short_id, video_id)
    _relaunch(short_id)
    return Response(status_code=202)
```

> `cancel_run` sets `cancelled=True`; the orchestrator checks `_is_cancelled` at each checkpoint and exits. A regen after cancel should clear `cancelled` — add `run.cancelled = False` inside `_relaunch` (load run, clear flag, commit) so a resumed/regen'd run isn't immediately stopped. Add a test for that if you extend it.

Run: `cd agent && python -m pytest tests/test_video_pipeline_regen_routes.py -q` and the full suite.

- [ ] **Step 3: Commit**

```bash
git add agent/flowboard/routes/video_pipeline.py agent/tests/test_video_pipeline_regen_routes.py
git commit -m "feat(video-pipeline): regen/cancel/scene-edit routes + relaunch"
```

---

### Task 6.3: Resume detection (list runs + ResumeBanner data)

`GET /runs?status=` lists runs; the frontend uses `status in {resolving,generating,merging}` to show a ResumeBanner. Resume itself is just `POST /runs/{sid}/start` (idempotent orchestrator). No auto-resume.

**Files:**
- Modify: `agent/flowboard/routes/video_pipeline.py`
- Create: `agent/tests/test_video_pipeline_list_runs.py`

- [ ] **Step 1: Write the failing test**

Write to `agent/tests/test_video_pipeline_list_runs.py`:

```python
from sqlmodel import select

from flowboard.db.session import get_session
from flowboard.db.video_pipeline_models import VideoPipelineRun
from flowboard.services.video_pipeline import run_builder


def _mk(status):
    run = run_builder.create_run(type_key="product_review", inputs={
        "character": {"source": "upload", "media_id": "c"},
        "background": {"source": "upload", "media_id": "b"},
        "products": [{"source": "upload", "media_id": "p0"}],
        "script_brief": "x", "aspect_ratio": "9:16",
        "video_count": 1, "scene_count": 1})
    with get_session() as s:
        r = s.get(VideoPipelineRun, run.id)
        r.status = status; s.add(r); s.commit()
    return run.short_id


def test_list_all_runs(client):
    _mk("done"); _mk("generating")
    r = client.get("/api/video-pipeline/runs")
    assert r.status_code == 200
    assert len(r.json()) >= 2


def test_list_filter_by_status(client):
    _mk("done"); gen = _mk("generating")
    r = client.get("/api/video-pipeline/runs?status=generating")
    assert r.status_code == 200
    sids = [x["short_id"] for x in r.json()]
    assert gen in sids
    assert all(x["status"] == "generating" for x in r.json())
```

- [ ] **Step 2: Implement list endpoint**

Add to `agent/flowboard/routes/video_pipeline.py`:

```python
from typing import Optional as _Optional  # if not already imported


@router.get("/runs")
def list_runs(status: _Optional[str] = None):
    with get_session() as s:
        q = select(VideoPipelineRun).order_by(VideoPipelineRun.id.desc())
        if status:
            q = q.where(VideoPipelineRun.status == status)
        runs = s.exec(q).all()
        return [
            {"short_id": r.short_id, "status": r.status, "type_key": r.type_key,
             "created_at": r.created_at, "finished_at": r.finished_at,
             "error": r.error}
            for r in runs
        ]
```

> Route ordering: FastAPI matches in declaration order. `GET /runs` (no path param) must be declared so it doesn't shadow `GET /runs/{short_id}`. Static segment `/runs` vs `/runs/{short_id}` don't collide, but keep `/runs` listing above `/runs/{short_id}` to be safe, and ensure `/runs/{short_id}` isn't accidentally matching `runs` as an id elsewhere.

Run: `cd agent && python -m pytest tests/test_video_pipeline_list_runs.py -q`.

- [ ] **Step 3: Commit**

```bash
git add agent/flowboard/routes/video_pipeline.py agent/tests/test_video_pipeline_list_runs.py
git commit -m "feat(video-pipeline): list runs + status filter (resume detection)"
```

---

### Task 6.4: Frontend — regen buttons, scene-prompt inline edit, cancel, runs list + ResumeBanner

**Files:**
- Modify: `frontend/src/api/client.ts` (regen/cancel/scene-patch/list functions)
- Modify: `frontend/src/video-pipeline/pages/PipelineRunDetailPage.tsx` (action buttons + inline edit + cancel)
- Modify: `frontend/src/video-pipeline/pages/PipelineRunsPage.tsx` (runs list + ResumeBanner)
- Modify: `frontend/src/styles.css`

- [ ] **Step 1: Add client functions**

In `frontend/src/api/client.ts`:

```typescript
export function vpCancelRun(shortId: string) {
  return api<{ cancelled: boolean }>(`/api/video-pipeline/runs/${shortId}/cancel`, { method: "POST" });
}
export function vpPatchScene(shortId: string, sceneId: number, body: { image_prompt?: string; video_prompt?: string }) {
  return api<{ ok: boolean }>(`/api/video-pipeline/runs/${shortId}/scenes/${sceneId}`, {
    method: "PATCH", body: JSON.stringify(body) });
}
async function vpPost202(path: string) {
  const r = await fetch(path, { method: "POST" });
  if (r.status === 409) throw new Error("đang chạy, thử lại sau");
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
}
export const vpRegenStoryboard = (sid: string, sceneId: number) =>
  vpPost202(`/api/video-pipeline/runs/${sid}/scenes/${sceneId}/regen-storyboard`);
export const vpRegenClip = (sid: string, sceneId: number) =>
  vpPost202(`/api/video-pipeline/runs/${sid}/scenes/${sceneId}/regen-clip`);
export const vpRegenComposite = (sid: string, videoId: number) =>
  vpPost202(`/api/video-pipeline/runs/${sid}/videos/${videoId}/regen-composite`);
export const vpRegenAll = (sid: string, videoId: number) =>
  vpPost202(`/api/video-pipeline/runs/${sid}/videos/${videoId}/regen-all`);
export const vpRemerge = (sid: string, videoId: number) =>
  vpPost202(`/api/video-pipeline/runs/${sid}/videos/${videoId}/remerge`);
export function vpListRuns(status?: string) {
  const q = status ? `?status=${encodeURIComponent(status)}` : "";
  return api<Array<{ short_id: string; status: string; type_key: string; created_at: string; finished_at: string | null; error: string | null }>>(
    `/api/video-pipeline/runs${q}`);
}
```

- [ ] **Step 2: Progress-page actions**

In `PipelineRunDetailPage.tsx`: add a Cancel button in the header (calls `vpCancelRun` then keeps polling — status flips to `cancelled`). On each scene card add "↻ storyboard" / "↻ clip" buttons (call regen fns, then `refreshOnce`); disable them when `sc.status` ends with `_running`. Make `image_prompt`/`video_prompt` editable inline (an "✎ sửa" toggle → textareas → save via `vpPatchScene`); disable when running. On each video card add "↻ Regen ảnh gốc" (composite), "↻ Regen video" (regen-all), and "Remerge" — composite/all show a confirm ("sẽ reset toàn bộ scene của video"). After any regen call, the polling loop resumes automatically (the relaunched orchestrator updates DB). Surface 409 errors as a transient toast/inline message.

- [ ] **Step 3: Runs list + ResumeBanner**

Replace `PipelineRunsPage.tsx`: fetch `vpListRuns()` on mount. Render a table of runs (short_id link → `/video-pipeline/runs/{sid}`, status badge, created/finished). At the top, if any run has status in `{resolving, generating, merging}`, show a **ResumeBanner** listing them with a "Resume" button that calls `vpStartRun(sid)` then navigates to the detail page. No auto-resume.

- [ ] **Step 4: Styles + lint + manual verify + commit**

```bash
cd frontend && npm run lint
```
Manual: regen a clip (storyboard kept, clip re-renders); regen composite (whole video resets, confirm dialog); edit a scene prompt then regen storyboard (new prompt used); cancel mid-run (no new clips appear); kill the app mid-run, restart → ResumeBanner appears → Resume continues.

```bash
git add frontend/src/api/client.ts frontend/src/video-pipeline/pages/PipelineRunDetailPage.tsx frontend/src/video-pipeline/pages/PipelineRunsPage.tsx frontend/src/styles.css
git commit -m "feat(video-pipeline): regen/cancel/edit UI + runs list + ResumeBanner"
```

---

### Task 6.5: Startup resume hook (surface interrupted runs; no auto-run)

On app startup, interrupted runs (status in `{resolving, generating, merging}`) remain in that state in the DB — the ResumeBanner already surfaces them via `GET /runs?status=`. No backend change is strictly required, but add a startup log line so operators see how many runs are resumable.

**Files:**
- Modify: `agent/flowboard/main.py` (log resumable count in lifespan)
- Create: `agent/tests/test_video_pipeline_resume_query.py`

- [ ] **Step 1: Write the failing test**

Write to `agent/tests/test_video_pipeline_resume_query.py`:

```python
from sqlmodel import select

from flowboard.db.session import get_session
from flowboard.db.video_pipeline_models import VideoPipelineRun
from flowboard.services.video_pipeline import run_builder
from flowboard.services.video_pipeline.resume import find_resumable


def _mk(status):
    run = run_builder.create_run(type_key="product_review", inputs={
        "character": {"source": "upload", "media_id": "c"},
        "background": {"source": "upload", "media_id": "b"},
        "products": [{"source": "upload", "media_id": "p0"}],
        "script_brief": "x", "aspect_ratio": "9:16",
        "video_count": 1, "scene_count": 1})
    with get_session() as s:
        r = s.get(VideoPipelineRun, run.id)
        r.status = status; s.add(r); s.commit()
    return run.short_id


def test_find_resumable_returns_in_progress_only():
    _mk("done"); a = _mk("generating"); b = _mk("merging"); _mk("failed")
    ids = set(find_resumable())
    assert a in ids and b in ids
```

- [ ] **Step 2: Implement resume helper + startup log**

Write to `agent/flowboard/services/video_pipeline/resume.py`:

```python
"""Detect runs that were interrupted mid-flight. Surface only — the user
clicks Resume (POST /runs/{sid}/start); we never auto-resume."""
from __future__ import annotations

from sqlmodel import select

from flowboard.db.session import get_session
from flowboard.db.video_pipeline_models import VideoPipelineRun

_RESUMABLE = ("resolving", "generating", "merging")


def find_resumable() -> list[str]:
    with get_session() as s:
        runs = s.exec(select(VideoPipelineRun).where(
            VideoPipelineRun.status.in_(_RESUMABLE))).all()
        return [r.short_id for r in runs]
```

In `main.py` lifespan, after `seed_builtins()`:

```python
from flowboard.services.video_pipeline.resume import find_resumable
_resumable = find_resumable()
if _resumable:
    logger.info("video-pipeline: %d resumable run(s): %s", len(_resumable), _resumable)
```

Run: `cd agent && python -m pytest tests/test_video_pipeline_resume_query.py -q`.

- [ ] **Step 3: Commit**

```bash
git add agent/flowboard/services/video_pipeline/resume.py agent/flowboard/main.py agent/tests/test_video_pipeline_resume_query.py
git commit -m "feat(video-pipeline): resume detection helper + startup log"
```

---

## Phase 7 — Frontend test infra + key tests + delete-run cleanup + template modal + manual QA

**Outcome:** A working vitest + Testing Library + msw setup with smoke/behavior tests for the wizard, InputCard, run store, and template modal; a delete-run endpoint that cleans files; the template-management modal; and a documented manual-QA pass.

### Task 7.1: Stand up frontend test infrastructure

**Files:**
- Modify: `frontend/package.json` (devDeps + `test` script)
- Create: `frontend/vitest.config.ts`
- Create: `frontend/src/test/setup.ts`
- Create: `frontend/src/test/msw-server.ts`

- [ ] **Step 1: Install dev dependencies**

From `frontend/`:
```bash
npm install -D vitest @testing-library/react @testing-library/user-event @testing-library/jest-dom jsdom msw
```

- [ ] **Step 2: Add the test script**

In `frontend/package.json` scripts, add:
```json
"test": "vitest run",
"test:watch": "vitest"
```

- [ ] **Step 3: vitest config**

Write to `frontend/vitest.config.ts`:

```typescript
import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
  },
});
```

> Confirm `@vitejs/plugin-react` is already a devDependency (the Vite app uses it). If the project uses `@vitejs/plugin-react-swc`, import that instead. Check `frontend/vite.config.ts` for which plugin is configured and match it.

- [ ] **Step 4: Test setup + msw server**

Write to `frontend/src/test/setup.ts`:

```typescript
import "@testing-library/jest-dom/vitest";
import { afterAll, afterEach, beforeAll } from "vitest";
import { server } from "./msw-server";

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());
```

Write to `frontend/src/test/msw-server.ts`:

```typescript
import { setupServer } from "msw/node";

export const server = setupServer();
```

- [ ] **Step 5: Sanity test + commit**

Write `frontend/src/test/sanity.test.ts`:

```typescript
import { describe, it, expect } from "vitest";
describe("test infra", () => {
  it("runs", () => { expect(1 + 1).toBe(2); });
});
```

```bash
cd frontend && npm test
```
Expect 1 passing test.

```bash
git add frontend/package.json frontend/package-lock.json frontend/vitest.config.ts frontend/src/test/
git commit -m "test(video-pipeline): stand up vitest + testing-library + msw"
```

---

### Task 7.2: Wizard store + validation tests

**Files:**
- Create: `frontend/src/video-pipeline/store.test.ts`

- [ ] **Step 1: Write the tests**

Write to `frontend/src/video-pipeline/store.test.ts`:

```typescript
import { describe, it, expect, beforeEach } from "vitest";
import { useWizardStore, wizardToInputs } from "./store";

beforeEach(() => useWizardStore.getState().reset());

describe("wizard store", () => {
  it("starts invalid (no media)", () => {
    expect(useWizardStore.getState().isValid()).toBe(false);
  });

  it("becomes valid when all inputs + brief present", () => {
    const s = useWizardStore.getState();
    s.setCharacter({ source: "upload", media_id: "c" });
    s.setBackground({ source: "upload", media_id: "b" });
    s.setProduct(0, { source: "upload", media_id: "p0" });
    s.setField("scriptBrief", "demo");
    expect(useWizardStore.getState().isValid()).toBe(true);
  });

  it("invalid if a product lacks media", () => {
    const s = useWizardStore.getState();
    s.setCharacter({ source: "upload", media_id: "c" });
    s.setBackground({ source: "upload", media_id: "b" });
    s.setField("scriptBrief", "demo");
    s.addProduct(); // second product empty
    s.setProduct(0, { source: "upload", media_id: "p0" });
    expect(useWizardStore.getState().isValid()).toBe(false);
  });

  it("add/remove product", () => {
    const s = useWizardStore.getState();
    s.addProduct();
    expect(useWizardStore.getState().products.length).toBe(2);
    s.removeProduct(1);
    expect(useWizardStore.getState().products.length).toBe(1);
  });

  it("loadTemplateParams maps snake_case", () => {
    useWizardStore.getState().loadTemplateParams({
      aspect_ratio: "16:9", scene_count: 5, video_count: 3, quality: "high",
    });
    const s = useWizardStore.getState();
    expect(s.aspectRatio).toBe("16:9");
    expect(s.sceneCount).toBe(5);
    expect(s.videoCount).toBe(3);
  });

  it("wizardToInputs produces snake_case payload", () => {
    const s = useWizardStore.getState();
    s.setCharacter({ source: "upload", media_id: "c" });
    s.setBackground({ source: "upload", media_id: "b" });
    s.setProduct(0, { source: "upload", media_id: "p0" });
    s.setField("scriptBrief", "demo");
    const inputs = wizardToInputs(useWizardStore.getState());
    expect(inputs.script_brief).toBe("demo");
    expect((inputs.products as unknown[]).length).toBe(1);
    expect(inputs.video_count).toBeDefined();
  });
});
```

Run: `cd frontend && npm test -- store.test`. Expect pass (fix store if a test exposes a bug — TDD).

- [ ] **Step 2: Commit**

```bash
git add frontend/src/video-pipeline/store.test.ts
git commit -m "test(video-pipeline): wizard store + validation unit tests"
```

---

### Task 7.3: Component tests — wizard gating, InputCard, run store polling

**Files:**
- Create: `frontend/src/video-pipeline/pages/PipelineNewPage.test.tsx`
- Create: `frontend/src/video-pipeline/components/InputCard.test.tsx`
- Create: `frontend/src/video-pipeline/runStore.test.ts`

- [ ] **Step 1: Wizard gating test**

Write to `frontend/src/video-pipeline/pages/PipelineNewPage.test.tsx`:

```tsx
import { describe, it, expect, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { PipelineNewPage } from "./PipelineNewPage";
import { useWizardStore } from "../store";

beforeEach(() => useWizardStore.getState().reset());

describe("PipelineNewPage", () => {
  it("disables Bắt đầu when inputs incomplete", () => {
    render(<MemoryRouter><PipelineNewPage /></MemoryRouter>);
    const btn = screen.getByTestId("vp-start-btn") as HTMLButtonElement;
    expect(btn.disabled).toBe(true);
  });

  it("enables Bắt đầu when wizard valid", () => {
    const s = useWizardStore.getState();
    s.setCharacter({ source: "upload", media_id: "c" });
    s.setBackground({ source: "upload", media_id: "b" });
    s.setProduct(0, { source: "upload", media_id: "p0" });
    s.setField("scriptBrief", "demo");
    render(<MemoryRouter><PipelineNewPage /></MemoryRouter>);
    const btn = screen.getByTestId("vp-start-btn") as HTMLButtonElement;
    expect(btn.disabled).toBe(false);
  });
});
```

> The wizard reads the store reactively; setting state before render reflects in the rendered button. If the page subscribes via `useWizardStore((s)=>...)` selectors, the pre-set state is visible on first render. If `isValid()` is called outside a selector and doesn't re-render, wrap the disabled check in a selector (`useWizardStore((s) => s.isValid())`) — adjust the page accordingly so the test reflects real reactivity.

- [ ] **Step 2: InputCard test (msw mocks resolve + upload)**

Write to `frontend/src/video-pipeline/components/InputCard.test.tsx`:

```tsx
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { server } from "../../test/msw-server";
import { InputCard } from "./InputCard";

describe("InputCard", () => {
  it("switches tabs", async () => {
    render(<InputCard label="Nhân vật" kind="character"
      value={{ source: "upload", media_id: null }} aspectRatio="9:16" onChange={() => {}} />);
    await userEvent.click(screen.getByText("AI tạo"));
    expect(screen.getByPlaceholderText(/Mô tả ngắn/)).toBeInTheDocument();
  });

  it("ai_gen calls resolve and shows variants, choosing one fires onChange", async () => {
    server.use(
      http.post("/api/video-pipeline/inputs/resolve", () =>
        HttpResponse.json({ media_entries: [{ media_id: "v1", url: "/media/v1" }] })),
    );
    // ensureProjectId hits the generation store; stub it.
    const onChange = vi.fn();
    render(<InputCard label="Nhân vật" kind="character"
      value={{ source: "upload", media_id: null }} aspectRatio="9:16" onChange={onChange} />);
    await userEvent.click(screen.getByText("AI tạo"));
    await userEvent.type(screen.getByPlaceholderText(/Mô tả ngắn/), "thân thiện");
    await userEvent.click(screen.getByText("Tạo 4 ảnh"));
    // variant appears
    const variant = await screen.findByAltText("variant");
    await userEvent.click(variant);
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ media_id: "v1" }));
  });
});
```

> `InputCard.handleAiGen` calls `useGenerationStore.getState().ensureProjectId()` which makes a network call. In the test, either (a) mock that endpoint via msw, or (b) `vi.spyOn(useGenerationStore.getState(), "ensureProjectId").mockResolvedValue("proj")`. Pick whichever matches how `ensureProjectId` is implemented; document it in the test. If `ensureProjectId` reads a cached id, seed it: `useGenerationStore.setState({ projectId: "proj" })`.

- [ ] **Step 3: Run store polling test (fake timers)**

Write to `frontend/src/video-pipeline/runStore.test.ts`:

```typescript
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { http, HttpResponse } from "msw";
import { server } from "../test/msw-server";
import { useRunStore } from "./runStore";

beforeEach(() => { useRunStore.setState({ run: null, error: null, pollTimer: null }); });
afterEach(() => { useRunStore.getState().stop(); });

describe("runStore polling", () => {
  it("refreshOnce loads run", async () => {
    server.use(http.get("/api/video-pipeline/runs/vpr_x", () =>
      HttpResponse.json({
        short_id: "vpr_x", type_key: "product_review", flow_project_id: null,
        inputs: {}, status: "generating", error: null, cancelled: false,
        products: [], progress: { clips_total: 0, clips_done: 0 },
      })));
    await useRunStore.getState().refreshOnce("vpr_x");
    expect(useRunStore.getState().run?.status).toBe("generating");
  });

  it("stops polling on terminal status", async () => {
    server.use(http.get("/api/video-pipeline/runs/vpr_done", () =>
      HttpResponse.json({
        short_id: "vpr_done", type_key: "product_review", flow_project_id: null,
        inputs: {}, status: "done", error: null, cancelled: false,
        products: [], progress: { clips_total: 1, clips_done: 1 },
      })));
    useRunStore.getState().start("vpr_done");
    await vi.waitFor(() => expect(useRunStore.getState().run?.status).toBe("done"));
    expect(useRunStore.getState().pollTimer).toBeNull();
  });
});
```

Run: `cd frontend && npm test`. Expect all green (adjust tests/impl together per TDD).

- [ ] **Step 4: Commit**

```bash
git add frontend/src/video-pipeline/pages/PipelineNewPage.test.tsx frontend/src/video-pipeline/components/InputCard.test.tsx frontend/src/video-pipeline/runStore.test.ts
git commit -m "test(video-pipeline): wizard gating, InputCard, run-store polling tests"
```

---

### Task 7.4: Delete-run endpoint + file cleanup

**Files:**
- Modify: `agent/flowboard/routes/video_pipeline.py`
- Create: `agent/tests/test_video_pipeline_delete_run.py`

- [ ] **Step 1: Write the failing test**

Write to `agent/tests/test_video_pipeline_delete_run.py`:

```python
from sqlmodel import select

from flowboard.db.session import get_session
from flowboard.db.video_pipeline_models import (
    VideoPipelineRun, VideoPipelineScene,
)
from flowboard.services.video_pipeline import run_builder, storage


def test_delete_run_removes_rows_and_files(client, monkeypatch, tmp_path):
    monkeypatch.setattr(storage, "STORAGE_DIR", tmp_path)
    run = run_builder.create_run(type_key="product_review", inputs={
        "character": {"source": "upload", "media_id": "c"},
        "background": {"source": "upload", "media_id": "b"},
        "products": [{"source": "upload", "media_id": "p0"}],
        "script_brief": "x", "aspect_ratio": "9:16",
        "video_count": 1, "scene_count": 1})
    storage.ensure_run_dirs(run.short_id)
    base = storage.run_dir(run.short_id)
    assert base.exists()

    r = client.delete(f"/api/video-pipeline/runs/{run.short_id}")
    assert r.status_code == 204

    with get_session() as s:
        gone = s.exec(select(VideoPipelineRun).where(
            VideoPipelineRun.short_id == run.short_id)).first()
        scenes = s.exec(select(VideoPipelineScene).where(
            VideoPipelineScene.run_id == run.id)).all()
    assert gone is None
    assert scenes == []
    assert not base.exists()


def test_delete_missing_run_404(client):
    r = client.delete("/api/video-pipeline/runs/vpr_nope")
    assert r.status_code == 404
```

- [ ] **Step 2: Implement delete**

Add to `agent/flowboard/routes/video_pipeline.py`:

```python
import shutil
from flowboard.db.video_pipeline_models import VideoPipelineProduct
from flowboard.services.video_pipeline import storage as _vp_storage


@router.delete("/runs/{short_id}", status_code=204)
def delete_run(short_id: str):
    with get_session() as s:
        run = s.exec(select(VideoPipelineRun).where(
            VideoPipelineRun.short_id == short_id)).first()
        if run is None:
            raise HTTPException(status_code=404, detail="run not found")
        rid = run.id
        for model in (VideoPipelineScene, VideoPipelineVideo, VideoPipelineProduct):
            for row in s.exec(select(model).where(model.run_id == rid)).all():
                s.delete(row)
        s.delete(run)
        s.commit()
    # best-effort file cleanup
    base = _vp_storage.run_dir(short_id)
    if base.exists():
        shutil.rmtree(base, ignore_errors=True)
    return Response(status_code=204)
```

> A running orchestrator task may still hold the run; in v1 deletion of an active run is the user's responsibility (cancel first). Optionally guard: refuse 409 if `short_id in _active_vp_tasks`. Add that guard + a test if you want the stricter behavior.

Run: `cd agent && python -m pytest tests/test_video_pipeline_delete_run.py -q`.

- [ ] **Step 3: Commit**

```bash
git add agent/flowboard/routes/video_pipeline.py agent/tests/test_video_pipeline_delete_run.py
git commit -m "feat(video-pipeline): delete run + file cleanup"
```

---

### Task 7.5: Template-management modal (frontend)

**Files:**
- Create: `frontend/src/video-pipeline/components/TemplateModal.tsx`
- Modify: `frontend/src/video-pipeline/pages/PipelineNewPage.tsx` (wire "📂 Tải template" / "💾 Lưu template")
- Create: `frontend/src/video-pipeline/components/TemplateModal.test.tsx`

- [ ] **Step 1: Test (msw mocks template CRUD)**

Write to `frontend/src/video-pipeline/components/TemplateModal.test.tsx`:

```tsx
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { server } from "../../test/msw-server";
import { TemplateModal } from "./TemplateModal";

describe("TemplateModal", () => {
  it("lists templates and disables edit/delete for builtins", async () => {
    server.use(http.get("/api/video-pipeline/templates", () =>
      HttpResponse.json([
        { id: 1, name: "Builtin", type_key: "product_review", params: {}, is_builtin: true, position: 0 },
        { id: 2, name: "Mine", type_key: "product_review", params: {}, is_builtin: false, position: 1 },
      ])));
    render(<TemplateModal onClose={() => {}} onLoad={() => {}} />);
    expect(await screen.findByText("Builtin")).toBeInTheDocument();
    expect(screen.getByText("Mine")).toBeInTheDocument();
    // builtin delete button disabled
    const delBtns = screen.getAllByTestId(/tpl-delete-/);
    const builtinDel = delBtns.find((b) => b.getAttribute("data-testid") === "tpl-delete-1") as HTMLButtonElement;
    expect(builtinDel.disabled).toBe(true);
  });

  it("loads a template's params via onLoad", async () => {
    server.use(http.get("/api/video-pipeline/templates", () =>
      HttpResponse.json([{ id: 2, name: "Mine", type_key: "product_review",
        params: { scene_count: 5 }, is_builtin: false, position: 0 }])));
    const onLoad = vi.fn();
    render(<TemplateModal onClose={() => {}} onLoad={onLoad} />);
    await userEvent.click(await screen.findByTestId("tpl-load-2"));
    expect(onLoad).toHaveBeenCalledWith(expect.objectContaining({ scene_count: 5 }));
  });
});
```

- [ ] **Step 2: Implement TemplateModal**

Write `frontend/src/video-pipeline/components/TemplateModal.tsx`: fetch `vpListTemplates()`; render each with Load (calls `onLoad(params)`), Delete (`vpDeleteTemplate`, disabled when `is_builtin`), and Rename (`vpPatchTemplate`, disabled when builtin). A "Save current as template" field calls `vpCreateTemplate`. `data-testid="tpl-load-{id}"`, `tpl-delete-{id}` etc. for the tests.

Wire into `PipelineNewPage`: "📂 Tải template" opens the modal with `onLoad={(p)=>useWizardStore.getState().loadTemplateParams(p)}`; "💾 Lưu template" calls `vpCreateTemplate({name, params: wizardParamsOnly(s)})` where `wizardParamsOnly` extracts only the param fields (no media).

Run: `cd frontend && npm test`.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/video-pipeline/components/TemplateModal.tsx frontend/src/video-pipeline/components/TemplateModal.test.tsx frontend/src/video-pipeline/pages/PipelineNewPage.tsx
git commit -m "feat(video-pipeline): template-management modal + tests"
```

---

### Task 7.6: Full regression + manual QA pass

**Files:** none (verification task). Optionally create `docs/superpowers/plans/2026-05-31-video-pipeline-qa.md` to record results.

- [ ] **Step 1: Backend regression**

```bash
cd agent && python -m pytest -q
```
Expect all green, including the existing (non-video-pipeline) suite.

- [ ] **Step 2: Frontend checks**

```bash
cd frontend && npm run lint && npm test
```
Expect type-check clean and all vitest tests green.

- [ ] **Step 3: Manual QA (full stack, real Flow creds)**

Run the agent + frontend dev servers. Execute the spec's manual-QA checklist and record pass/fail:
1. Happy path 2 products × 2 videos × 3 scenes → 4 `.mp4` files that play in VLC.
2. AI-generate prompt+image for character/product/background → sensible images.
3. Template save then load (params populate; media not saved).
4. Regen at each level (clip / storyboard / composite / video / remerge) → correct cascade.
5. Crossfade 0 vs 0.4s → different file sizes / visible transition.
6. Close app mid-run → reopen → ResumeBanner → Resume → continues from where it stopped.
7. Cancel mid-run → status `cancelled`, no further clips emitted.

- [ ] **Step 4: Final commit (if QA doc created)**

```bash
git add docs/superpowers/plans/2026-05-31-video-pipeline-qa.md
git commit -m "docs(video-pipeline): manual QA results"
```

---

## Appendix — Cross-phase notes & open items to confirm during execution

These are flagged inline above but collected here so they aren't missed:

1. **`run_llm` provider key.** The plan uses `"claude"` as the provider name passed to `run_llm`. Confirm the registered key in `services/llm` (Task 2.1, 3.2). If different, change in `input_resolver.py` and `script_planner.py`.
2. **`gen_video` `video_quality` enum + `paygate_tier`.** Confirm accepted values and whether `paygate_tier` is required (Task 4.2). The SDK raised `ValueError` without a tier on some paths; thread the flow_client default through like `worker/processor.py` does.
3. **`media_service.ingest_urls` / `fetch_and_cache` exact signatures** (sync vs async, arg shape). Verify against `services/media.py` (Tasks 3.1, 5.3).
4. **`pytest-asyncio` mode.** Confirm `asyncio_mode` config; the plan uses `@pytest.mark.asyncio`. Match the repo's existing async-test convention (Task 2.1 onward).
5. **Table registration for `create_all`.** Confirm which module import triggers metadata registration so the new tables are created in tests and prod (Task 1.1, Step 3).
6. **`@vitejs/plugin-react` vs `-swc`.** Match `vite.config.ts` in the vitest config (Task 7.1).
7. **Clip durations for xfade.** v1 uses a `[2.0]*n` default; probe real durations with bundled `ffprobe` if crossfade offsets look wrong in manual QA (Task 5.2).
8. **`react-router` + Electron.** The desktop build loads the SPA via `file://` or a custom protocol. `BrowserRouter` may need to become `HashRouter` in the packaged app. Verify against the Electron loader in `desktop/` (Task 1.8). If the packaged app uses `file://`, switch to `HashRouter`.
9. **`/runs` route ordering.** Keep the `GET /runs` list endpoint from shadowing `GET /runs/{short_id}` (Task 6.3).

## Phase dependency / merge order

```
Phase 1 ──► Phase 2 ──► Phase 3 ──► Phase 4 ──► Phase 5 ──► Phase 6 ──► Phase 7
(schema)   (wizard)    (gen units) (orchestr.) (merge+dl)  (regen/    (tests +
                                    + polling)  USABLE)     resume)     QA)
```
Each phase is independently committable and leaves the app working. **Phase 5 is the usable milestone** — a user can produce and download `.mp4`. Phases 6–7 add robustness and the frontend test suite. Phases 1–5 should land before 6–7 but 6 and 7 can be developed in parallel by different workers (6 = robustness, 7 = tests/cleanup/template-modal) since they touch mostly different files (one route file overlap — coordinate merges).

