# Video Pipeline — Design Specification

**Date:** 2026-05-31
**Branch:** `feature/pipline-video-creator`
**Status:** Draft — pending user review before implementation planning

## Overview

**Video Pipeline** là feature tự động hoá quy trình tạo video marketing review sản phẩm theo dạng wizard: người dùng nhập nhân vật + nhiều sản phẩm + bối cảnh + prompt kịch bản + thông số → bấm "Bắt đầu" → hệ thống tự động, cho **từng sản phẩm**, sinh kịch bản, ghép ảnh nhân vật+sản phẩm, tạo storyboard từng phân cảnh, render clip từng phân cảnh bằng Veo 3.1 i2v, rồi ghép các clip thành 1 video hoàn chỉnh. Kết quả là các file `.mp4` tải về.

Điểm cốt lõi kiến trúc: hệ thống thiết kế quanh một **pipeline-type registry** có thể mở rộng. v1 hiện thực đúng 1 loại `product_review`; các loại khác (talking-head, unboxing, storytelling…) thêm sau bằng cách đăng ký thêm một type, **không sửa orchestrator hay UI lõi**.

> Lưu ý lịch sử: nhánh `feature/pipeline-wizard-templates` đã có một feature tương tự (`pipeline-studio`, 68 commit). Theo quyết định của user, feature này được **thiết kế lại từ đầu** trên nhánh hiện tại; nhánh cũ chỉ dùng để tham khảo, không merge.

## Goals & Non-Goals

### Goals
- Wizard 1 trang cho người dùng không cần học canvas.
- Hỗ trợ **nhiều sản phẩm** trong 1 run; mỗi sản phẩm sinh **n video (1–4)**, mỗi video có **kịch bản độc lập**.
- Quy trình ảnh 2 bước: (1) ghép nhân vật + sản phẩm → ảnh gốc/composite; (2) ghép composite + bối cảnh → storyboard mỗi phân cảnh.
- Consistency nhân vật + sản phẩm + bối cảnh qua multi-ref image generation.
- Ghép clip thành video hoàn chỉnh (ffmpeg concat / crossfade).
- Tái sử dụng tối đa hạ tầng hiện có (LLM CLI, Flow SDK gen_image/gen_video, ws_server, upload/media).
- Kiến trúc pipeline-type **mở rộng được**.
- Độ bền: regen từng phần, resume sau crash, hủy run, thư viện template.
- Tạo Flow (Veo3) project cho mỗi run.

### Non-Goals (v1)
- Materialize node lên canvas (chỉ xuất file .mp4 — quyết định của user).
- Bước review/confirm kịch bản trung gian (chạy tự động sau khi bấm "Bắt đầu").
- Voice-over / TTS custom (dùng audio Veo 3.1 tự sinh).
- Upload trực tiếp lên YouTube / TikTok.
- A/B variant cùng 1 phân cảnh (muốn variant → regen scene).
- Chia sẻ template giữa nhiều user (app local single-user).
- E2E Playwright (manual QA cho v1).

## Decisions Recap (chốt từ brainstorming)

| # | Topic | Decision |
|---|---|---|
| 1 | "Loại" pipeline | Nhiều **kiểu pipeline** khác nhau → pipeline-type registry mở rộng; v1 làm `product_review` |
| 2 | n video / sản phẩm | Mỗi video có **kịch bản độc lập** (n kịch bản khác nhau) |
| 3 | Đầu ra | **Chỉ file .mp4** tải về (không đụng canvas) |
| 4 | Độ bền v1 | Regen từng phần + Resume sau crash + Hủy run + Thư viện template |
| 5 | Ghép ảnh | 2 bước: composite (char+product) → storyboard (composite+background) |
| 6 | Flow project | Tạo 1 Flow project cho mỗi run |
| 7 | Wizard | 1 trang cuộn dọc, không stepper (vì chạy tự động sau "Bắt đầu") |
| 8 | Trang tiến độ | Nhóm Sản phẩm → Video → Scene; có progress bar tổng, composite riêng mỗi video, prompt từng scene xem/sửa tại chỗ |
| 9 | ffmpeg | `imageio-ffmpeg` portable binary qua subprocess (zero-install) |

---

## Section A — Architecture & Data model

### A.1 — Routing

App hiện là single-page (canvas). Giới thiệu `react-router-dom` v6, bọc canvas vào route `/` (không đổi hành vi), thêm các route mới:

| Route | Trang |
|---|---|
| `/` | Canvas hiện tại (không đổi) |
| `/video-pipeline/new` | Wizard tạo pipeline |
| `/video-pipeline/runs` | Danh sách run + ResumeBanner |
| `/video-pipeline/runs/:shortId` | Trang tiến độ + regen |

Sidebar trái thêm mục **"Video Pipeline"**.

### A.2 — Data flow tổng quát

```
Wizard UI (/video-pipeline/new)
    │ POST /api/video-pipeline/runs
    ▼
VideoPipelineRun + N product + (N×n) video + (N×n×M) scene rows
    │ POST /runs/{sid}/start  → asyncio.create_task(orchestrator.run(id))
    ▼
services/video_pipeline/orchestrator.run(run_id)   (idempotent, resume-safe)
    │  0. ensure flow_project_id (create_project)
    │  1. resolve inputs (character, products[], background) → media_id
    │  2. PER PRODUCT:
    │       a. composite_gen: gen_image(refs=[char, product], variant_count=n) → n ảnh gốc
    │       b. PER VIDEO (sem=cap):
    │            - script_planner (LLM)  → script_json (M scene) [độc lập]
    │            - PER SCENE (sem): storyboard_gen → clip_gen
    │            - khi M clip done → merger → merged .mp4
    │  3. run.status = done
    ▼
Frontend subscribe WS `video-pipeline:{short_id}` để update realtime
```

### A.3 — Data model (SQLModel mới)

Prefix `VideoPipeline*` để tránh xung đột với `class PipelineRun` đã có trong `db/models.py` (cái cũ là execution của `Plan` thuộc canvas planner — không liên quan).

UTC datetime dùng `_utcnow()` helper hiện có. Migration: pattern Alembic / `init_db` như các bảng hiện tại.

#### `video_pipeline_template`
```python
class VideoPipelineTemplate(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    type_key: str                                   # "product_review"
    params: dict = Field(default_factory=dict, sa_column=Column(JSON))
    # params: aspect_ratio, scene_count, quality, crossfade_sec, audio_enabled,
    #         video_count, concurrency_cap, script_brief (KHÔNG lưu media input)
    is_builtin: bool = False                         # True = ship-with-app, không cho sửa/xóa
    position: int = 0
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)
```
Seed vài builtin idempotent ở startup nếu bảng trống.

#### `video_pipeline_run`
```python
class VideoPipelineRun(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    short_id: str = Field(index=True, unique=True)   # "vpr_8x4kp"
    type_key: str = "product_review"

    flow_project_id: Optional[str] = None            # tạo qua flow_sdk.create_project

    inputs: dict = Field(default_factory=dict, sa_column=Column(JSON))
    # {
    #   "character": {"source":"upload|gen|ai_gen", "media_id":"...", "prompt":"..."},
    #   "background":{... same},
    #   "script_brief": "định hướng nội dung video (prompt kịch bản)",
    #   "aspect_ratio": "9:16",
    #   "video_count": 2,          # n video / sản phẩm
    #   "scene_count": 3,          # M phân cảnh / video
    #   "quality": "standard",     # fast|standard|high
    #   "crossfade_sec": 0.4,
    #   "audio_enabled": true,
    #   "concurrency_cap": 4
    # }

    status: str = "pending"
    # pending → resolving → generating → merging → done
    #                                              ↘ failed | cancelled
    error: Optional[str] = None
    cancelled: bool = False

    created_at: datetime = Field(default_factory=_utcnow)
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
```

#### `video_pipeline_product`
```python
class VideoPipelineProduct(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    run_id: int = Field(foreign_key="videopipelinerun.id", index=True)
    product_index: int
    source: str                                      # upload|gen|ai_gen
    media_id: Optional[str] = None
    prompt: Optional[str] = None
    __table_args__ = (UniqueConstraint("run_id", "product_index",
                                       name="uq_run_product"),)
```

#### `video_pipeline_video`
```python
class VideoPipelineVideo(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    run_id: int = Field(foreign_key="videopipelinerun.id", index=True)
    product_index: int
    video_index: int                                 # 0..n-1 trong phạm vi product

    composite_media_id: Optional[str] = None         # ảnh gốc char+product (1 variant cho video này)
    merged_local_path: Optional[str] = None
    merged_url: Optional[str] = None

    status: str = "pending"
    # pending → composite_done → scripted → scenes_done → merging → done | failed
    error: Optional[str] = None
    duration_sec: Optional[float] = None
    file_size_bytes: Optional[int] = None
    composite_attempts: int = 0
    updated_at: datetime = Field(default_factory=_utcnow)

    __table_args__ = (UniqueConstraint("run_id", "product_index", "video_index",
                                       name="uq_run_product_video"),)
```

#### `video_pipeline_scene`
```python
class VideoPipelineScene(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    run_id: int = Field(foreign_key="videopipelinerun.id", index=True)
    product_index: int
    video_index: int
    scene_index: int

    image_prompt: str = ""        # storyboard composition (composite + background)
    video_prompt: str = ""        # motion + action cho Veo i2v (≤ 25 words)

    storyboard_media_id: Optional[str] = None
    clip_media_id: Optional[str] = None

    status: str = "pending"
    # pending → storyboard_running → storyboard_done →
    #          clip_running → clip_done → merged
    #          ↘ failed
    error: Optional[str] = None
    storyboard_attempts: int = 0
    clip_attempts: int = 0
    updated_at: datetime = Field(default_factory=_utcnow)

    __table_args__ = (UniqueConstraint("run_id", "product_index", "video_index", "scene_index",
                                       name="uq_run_product_video_scene"),)
```

### A.4 — Storage layout

```
storage/
  video_pipeline/
    <run-short-id>/
      composites/p{i}-v{k}.png
      storyboards/p{i}-v{k}-s{j}.png
      clips/p{i}-v{k}-s{j}.mp4
      merged/p{i}-v{k}.mp4
      manifest.json         # snapshot run+products+videos+scenes — resume-safe
      run.log               # rotating 5MB
```
File input refs (character/products/background) vẫn nằm trong `storage/<media-id>` (managed bởi `Asset` table), không copy vào `video_pipeline/`.

---

## Section B — Wizard UI + Trang tiến độ

(Mockup đã duyệt qua visual companion — xem `.superpowers/brainstorm/.../wizard-progress.html`, `progress-v2.html`.)

### B.1 — Wizard `/video-pipeline/new` (1 trang cuộn dọc, không stepper)

Thứ tự field:
1. **Loại pipeline** — dropdown (v1 chỉ `Product Review`).
2. **Nhân vật** — `InputCard` 3 tab: Upload / Gen từ prompt / AI tạo prompt+ảnh.
3. **Sản phẩm (nhiều)** — list card repeatable, "+ Thêm sản phẩm" / xóa; tối thiểu 1; mỗi card dùng InputCard pattern.
4. **Bối cảnh** — InputCard.
5. **Prompt kịch bản** — textarea định hướng nội dung.
6. **Thông số video** — tỉ lệ (9:16 / 1:1 / 16:9), số phân cảnh/video (M), chất lượng (Nhanh/Chuẩn/Cao), chuyển cảnh (0 / 0.4 / 0.8s), audio on/off.
7. **Số video / sản phẩm (n)** — pill 1–4.
8. **Nâng cao** (collapsible): concurrency cap.
9. Nút **"💾 Lưu template"** và **"▶ Bắt đầu"**; nút **"📂 Tải template"** ở header.

**InputCard** (dùng lại cho nhân vật, bối cảnh, từng sản phẩm): 3 tab nội bộ.
- *Upload*: chọn file → upload qua `routes/upload`.
- *Gen từ prompt*: nhập prompt → gen_image 4 variant → chọn 1.
- *AI tạo prompt+ảnh (1-shot)*: gõ mô tả ngắn → LLM CLI sinh full prompt → gen_image → chọn variant; **không có bước confirm prompt trung gian**.

"Bắt đầu" → `POST /runs` → `POST /runs/{sid}/start` → điều hướng `/video-pipeline/runs/{sid}`.

### B.2 — Trang tiến độ `/video-pipeline/runs/:shortId`

WS subscribe `video-pipeline:{short_id}`. Cấu trúc:
- **Run header**: short_id, status badge, time elapsed + ETA, nút Cancel, nút "⤓ Tải tất cả .zip", và **thanh tiến độ tổng** (`X/Y clip · %`).
- Nhóm **Sản phẩm** → trong mỗi sản phẩm là các **Video card**.
- Mỗi Video card:
  - **Composite (ảnh gốc) riêng**: ảnh ghép nhân vật+sản phẩm + nút "↻ Regen ảnh gốc" (cảnh báo reset toàn bộ scene của video).
  - **Scene card** (dọc theo tỉ lệ): thumbnail storyboard + thumbnail/preview clip + status; hiển thị **image_prompt + video_prompt** với nút "✎ sửa" tại chỗ; nút "↻ storyboard" / "↻ clip".
  - Khi video done → **MergedPreview** (`<video>` player) + nút Download; nút "↻ Regen video" / "Remerge".
- `/video-pipeline/runs`: list runs + **ResumeBanner** khi có run dở.

### B.3 — Template
- "Lưu template" → snapshot `{type_key, params}` (không lưu media input) vào `VideoPipelineTemplate`.
- "Tải template" → đổ params vào form.
- Modal "Quản lý template" (CRUD); builtin không cho sửa/xóa.

---

## Section C — Type registry, Orchestration, Regen/Resume & API

### C.1 — Pipeline-type registry

```python
# services/video_pipeline/types/base.py
class PipelineType(Protocol):
    key: str                  # "product_review"
    label: str                # "Product Review"
    input_schema: dict        # field bắt buộc (character, products[], background, script_brief)
    def build_video_steps(self, ctx) -> list[Step]   # composite → script → (storyboard→clip)* → merge
```
- v1 đăng ký 1 type trong `types/registry.py`: `REGISTRY = {"product_review": ProductReviewType()}`.
- Orchestrator generic: gọi `pipeline_type.build_video_steps()` rồi chạy. Thêm type mới = thêm 1 file + 1 dòng đăng ký, không sửa orchestrator/UI lõi.
- Wizard đọc `input_schema` để biết field nào cần (v1 render tĩnh cho product_review; field-driven là enhancement sau).

### C.2 — Module backend

```
agent/flowboard/services/video_pipeline/
  __init__.py
  orchestrator.py        # run(run_id): idempotent, resume-safe, concurrency cap
  types/
    base.py              # PipelineType protocol + Step
    registry.py          # REGISTRY
    product_review.py    # build_video_steps + prompt templates
  composite_gen.py       # gen_image(refs=[character, product], variant_count=n)
  script_planner.py      # LLM sinh kịch bản 1 video (M scene), JSON validate + retry
  storyboard_gen.py      # gen_image(refs=[composite, background], prompt=image_prompt)
  clip_gen.py            # gen_video i2v(start=storyboard, prompt=video_prompt)
  merger.py              # imageio-ffmpeg concat / xfade
  storage.py             # path helpers + manifest.json roundtrip
  state_machine.py       # transition rules + validators (pure, dễ test)
  events.py              # WS emit helpers
  resume.py              # detect + resume run dở
  templates.py           # template CRUD
```
Tái dùng: `flow_sdk` (create_project, gen_image, gen_video), `flow_client`, `services/llm`, `services/vision` (mô tả ảnh input cho LLM context), `ws_server`, `routes/upload` + `routes/media`.

### C.3 — Orchestrator flow

`POST /runs/{id}/start` → `asyncio.create_task(orchestrator.run(id))` (không block, restart-safe).
```
0. ensure flow_project_id  (create_project nếu chưa có) → cache trên run
1. resolve inputs (character, mỗi product, background) → media_id
2. PER PRODUCT:
   a. composite_gen: gen_image(refs=[char, product], variant_count=n) → n ảnh → gán mỗi ảnh cho 1 video
   b. PER VIDEO (song song, sem=cap):
        - script_planner → script_json (M scene)   [độc lập mỗi video]
        - PER SCENE (song song, sem):
             storyboard_gen → storyboard_media_id   (refs=[composite, background])
             clip_gen       → clip_media_id         (start_image=storyboard)
        - khi M clip done → merger → merged .mp4
3. run.status = done
```
- **Concurrency:** 1 `asyncio.Semaphore(cap)` dùng chung cho mọi lời gọi Flow (storyboard + clip); default cap=4.
- **Mỗi transition:** ghi DB → emit WS → cập nhật `manifest.json`.
- **Idempotent:** mỗi handler check status đầu hàm, skip nếu đã done → resume chỉ làm phần thiếu.

### C.4 — Phân loại lỗi & retry

| Loại | Ví dụ | Xử lý |
|---|---|---|
| Transient | Flow 429/503, network | backoff 1/2/4/8s, max 3 |
| Permanent per-scene | Veo chặn prompt, codec | `scene.status=failed`, run vẫn chạy tiếp |
| Permanent run-level | LLM CLI thiếu, DB chết | `run.status=failed`, dừng |
| Script JSON invalid | LLM trả sai format | re-prompt kèm feedback, max 2 |
| Cancel | user bấm | set `cancelled`, thoát ở checkpoint kế |

### C.5 — Regen (cascade reset)

| Mức | Reset gì |
|---|---|
| Regen clip (1 scene) | giữ storyboard, xóa clip + merged của video |
| Regen storyboard (1 scene) | xóa storyboard + clip + merged của video |
| Regen ảnh gốc / composite (1 video) | xóa composite + toàn bộ scene (storyboard+clip) + merged của video |
| Regen video (cả video) | reset toàn bộ video |
| Remerge | chỉ chạy lại merger (đổi crossfade) |

Guard: scene/video đang `*_running` → API trả 409. Frontend disable nút khi in-flight.

### C.6 — Resume

App khởi động → `SELECT runs WHERE status ∈ {resolving, generating, merging}` → nếu có, hiện **ResumeBanner** ở `/video-pipeline/runs`. User bấm Resume → `POST /runs/{id}/start` → orchestrator idempotent skip phần đã xong. **Không auto-resume ngầm.** ffmpeg ghi `*.tmp` rồi rename (atomic) để tránh file hỏng khi crash giữa merge.

### C.7 — API routes (`/api/video-pipeline`)

| Method | Path | Mô tả |
|---|---|---|
| GET | `/types` | List pipeline types (v1: product_review) |
| GET/POST/PATCH/DELETE | `/templates`, `/templates/{id}` | CRUD template (403 builtin) |
| POST | `/inputs/resolve` | `{kind, source, media_id?/prompt?, aspect_ratio}` → `{media_id, url}` |
| POST | `/runs` | tạo run + product + video + scene rows |
| POST | `/runs/{sid}/start` | kick orchestrator, 202 |
| POST | `/runs/{sid}/cancel` | set cancelled |
| GET | `/runs` `?status=` | list (resume banner dùng) |
| GET | `/runs/{sid}` | full detail |
| DELETE | `/runs/{sid}` | soft delete + cleanup files |
| PATCH | `/runs/{sid}/scenes/{id}` | sửa image/video_prompt |
| POST | `/runs/{sid}/scenes/{id}/regen-storyboard` · `/regen-clip` | regen scene |
| POST | `/runs/{sid}/videos/{id}/regen-composite` · `/regen-all` · `/remerge` | regen video |
| GET | `/runs/{sid}/videos/{id}/preview` · `/download` | stream inline / attachment |
| GET | `/runs/{sid}/download-all.zip` | zip tất cả video |
| WS | subscribe `video-pipeline:{sid}` | events realtime |

WebSocket events (reuse `services/ws_server.py`):
```json
{"type":"video-pipeline.run.status",   "run_id":"vpr_8x4kp", "status":"generating"}
{"type":"video-pipeline.scene.status", "run_id":"vpr_8x4kp", "product_idx":0, "video_idx":0, "scene_idx":1, "status":"clip_done", "media_id":"...", "url":"..."}
{"type":"video-pipeline.video.merged", "run_id":"vpr_8x4kp", "product_idx":0, "video_idx":0, "url":"..."}
{"type":"video-pipeline.run.done",     "run_id":"vpr_8x4kp"}
{"type":"video-pipeline.run.failed",   "run_id":"vpr_8x4kp", "error":"..."}
```

### C.8 — Merger

`imageio_ffmpeg.get_ffmpeg_exe()` (portable, no PATH dependency). 2 code path:
- `crossfade_sec == 0`: concat demuxer, không re-encode (instant).
- `crossfade_sec > 0`: `filter_complex` pairwise xfade + acrossfade (nếu audio on).
Ghi `*.tmp` → rename atomic.

---

## Section D — Testing strategy

### Backend (pytest)
Test files:
```
agent/tests/
  test_video_pipeline_state_machine.py     # property-based (hypothesis)
  test_video_pipeline_storage.py           # path helpers + manifest roundtrip
  test_video_pipeline_script_planner.py    # JSON validate + retry
  test_video_pipeline_composite_gen.py
  test_video_pipeline_storyboard_gen.py
  test_video_pipeline_clip_gen.py
  test_video_pipeline_merger.py
  test_video_pipeline_orchestrator.py      # happy + per-scene-fail + resume + cancel
  test_video_pipeline_regen.py             # cascade reset
  test_video_pipeline_routes.py
  test_video_pipeline_templates.py
```
Stubs: `MockFlowSDK` (pre-canned media_id, flag fail_next), `MockLLM` (pre-canned JSON), `MockFFmpeg` (patch subprocess, viết dummy mp4).

Integration scenarios:
1. Happy path: 2 SP × 2 video × 3 scene → 4 merged .mp4 path populated.
2. Per-scene fail không fail run.
3. Resume after crash (kill mid-run, restart, idempotent skip).
4. Regen composite cascade (assert scenes + merged reset).
5. Remerge crossfade khác (assert ffmpeg cmdline).
6. Cancel mid-run (in-flight finish, không enqueue thêm).

### Frontend (vitest + @testing-library/react + msw)
- Smoke render 3 trang (New / Runs / RunDetail).
- InputCard 3-tab switch + submit (msw mock `/inputs/resolve`).
- Wizard validation chặn "Bắt đầu" khi thiếu input (tối thiểu 1 sản phẩm).
- Template modal CRUD (builtin disabled).
- Zustand store actions.

### Manual QA
1. Happy path 2 SP × 2 video × 3 scene → 4 file .mp4 chạy được VLC.
2. AI tạo prompt+ảnh cho nhân vật/sản phẩm/bối cảnh → ảnh hợp lý.
3. Template save/load.
4. Regen từng mức (clip / storyboard / composite / video / remerge) cascade đúng.
5. Crossfade 0 vs 0.4s → file size khác kỳ vọng.
6. Close app mid-run → mở lại → ResumeBanner → resume → tiếp tục.
7. Cancel run → status=cancelled, không phát thêm clip.

---

## Risks & Mitigations

| Risk | Mitigation |
|---|---|
| Flow rate-limit 429 khi cap cao | backoff + retry; cho chỉnh cap trong Nâng cao |
| LLM CLI cold-start lag | script planner gọi gọn từng video; user thấy progress realtime |
| ffmpeg xfade re-encode lâu cho video dài | cho chọn crossfade=0 (concat demuxer instant) |
| Disk phình do intermediate files | DELETE run dọn `video_pipeline/<run-id>/`; cân nhắc "Archive" giữ merged |
| Drift consistency dù có composite | multi-ref cho storyboard (composite + background); regen scene riêng nếu xấu |
| App crash giữa merge → file hỏng | ffmpeg viết `*.tmp` rồi rename atomic; resume check existence |
| Số lượng job lớn (N SP × n video × M scene) | semaphore cap dùng chung; progress + ETA rõ ràng |

## Implementation Phases (preview)

Sẽ expand thành implementation plan riêng (qua writing-plans skill). Sơ bộ:

1. **Phase 1 — Schema + template CRUD + routing skeleton** (DB tables, migration, `/types` + `/templates`, react-router, sidebar entry).
2. **Phase 2 — Wizard Bước 1 + input_resolver** (InputCard 3 nguồn, multi-product UI, `POST /runs`).
3. **Phase 3 — Type registry + script_planner + composite_gen** (product_review type, LLM script per video, ảnh gốc).
4. **Phase 4 — storyboard_gen + clip_gen + orchestrator + WS** (trang tiến độ realtime).
5. **Phase 5 — Merger + download/zip + preview** (ffmpeg, hoàn tất đầu ra .mp4).
6. **Phase 6 — Regen flows + resume + cancel + error UI**.
7. **Phase 7 — Frontend test infra + key tests + manual QA**.

Mỗi phase độc lập, có thể merge sớm; user dùng được output .mp4 từ Phase 5.
