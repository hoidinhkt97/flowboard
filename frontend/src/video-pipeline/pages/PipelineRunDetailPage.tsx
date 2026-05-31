import { useEffect, useState, useRef } from "react";
import { useParams } from "react-router-dom";
import { useRunStore } from "../runStore";
import {
  vpCancelRun, vpDownloadAllUrl, vpVideoDownloadUrl,
  vpPatchScene, vpRegenStoryboard, vpRegenClip,
} from "../../api/client";

const TERMINAL = new Set(["done", "failed", "cancelled"]);
const RUNNING = new Set(["resolving", "generating", "storyboard_running", "clip_running", "merging"]);

const STATUS_VI: Record<string, string> = {
  pending: "Chờ xử lý", resolving: "Đang chuẩn bị…", generating: "● Generating",
  composite_done: "Ghép xong", scripted: "Đã có kịch bản",
  storyboard_running: "Tạo ảnh…", storyboard_done: "Ảnh xong",
  clip_running: "Tạo clip…", clip_done: "✓ hoàn tất", scenes_done: "Cảnh xong",
  merging: "Ghép video…", done: "✓ hoàn tất", failed: "Thất bại", cancelled: "Đã huỷ",
};

function sl(s: string) { return STATUS_VI[s] ?? s; }

function Thumb({ mediaId, aspect, placeholder, size = "md" }: {
  mediaId: string | null; aspect?: string; placeholder?: string; size?: "sm" | "md";
}) {
  const style: React.CSSProperties = aspect === "9:16"
    ? (size === "sm" ? { width: 74, height: 96 } : { width: 120, height: 213 })
    : { width: 74, height: 96 };
  return (
    <div className="vp2-thumb" style={style}>
      {mediaId
        ? <img src={`/media/${mediaId}`} alt="thumb" />
        : <span className="vp2-thumb__placeholder">{placeholder ?? "…"}</span>}
    </div>
  );
}

interface EditablePromptProps {
  label: string;
  value: string;
  disabled: boolean;
  onSave: (v: string) => Promise<void>;
}
function EditablePrompt({ label, value, disabled, onSave }: EditablePromptProps) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(value);
  const [saving, setSaving] = useState(false);
  const ref = useRef<HTMLTextAreaElement>(null);

  useEffect(() => { if (editing) ref.current?.focus(); }, [editing]);
  useEffect(() => { if (!editing) setDraft(value); }, [value, editing]);

  async function handleSave() {
    if (draft.trim() === value.trim()) { setEditing(false); return; }
    setSaving(true);
    try { await onSave(draft.trim()); setEditing(false); }
    catch { /* keep editing open */ }
    finally { setSaving(false); }
  }

  return (
    <div className="vp2-eprompt">
      <div className="vp2-eprompt__header">
        <span className="vp2-scene__prompt-label">{label}</span>
        {!editing && !disabled && (
          <button type="button" className="vp2-eprompt__edit-btn" onClick={() => setEditing(true)}>
            ✎ Sửa
          </button>
        )}
      </div>
      {editing ? (
        <div className="vp2-eprompt__editing">
          <textarea
            ref={ref}
            className="vp2-eprompt__textarea"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            rows={5}
          />
          <div className="vp2-eprompt__actions">
            <button type="button" className="vp2-eprompt__save" disabled={saving} onClick={handleSave}>
              {saving ? "Đang lưu…" : "Lưu"}
            </button>
            <button type="button" className="vp2-eprompt__cancel" onClick={() => setEditing(false)}>
              Huỷ
            </button>
          </div>
        </div>
      ) : (
        <div className="vp2-scene__prompt-box">{value || "—"}</div>
      )}
    </div>
  );
}

export function PipelineRunDetailPage() {
  const { shortId } = useParams<{ shortId: string }>();
  const run    = useRunStore((s) => s.run);
  const error  = useRunStore((s) => s.error);
  const start  = useRunStore((s) => s.start);
  const stop   = useRunStore((s) => s.stop);
  const refresh = useRunStore((s) => s.refreshOnce);

  const [cancelling, setCancelling] = useState(false);
  const [regenLoading, setRegenLoading] = useState<Record<string, boolean>>({});

  useEffect(() => {
    if (!shortId) return;
    start(shortId);
    return () => stop();
  }, [shortId, start, stop]);

  if (error && !run) return <div className="vp-page vp2-error" role="alert">Lỗi: {error}</div>;
  if (!run) return <div className="vp-page vp2-loading">Đang tải…</div>;

  const { clips_done, clips_total } = run.progress;
  const pct = clips_total ? Math.round((clips_done / clips_total) * 100) : 0;
  const isRunning = !TERMINAL.has(run.status);

  async function handleCancel() {
    if (!shortId || cancelling) return;
    setCancelling(true);
    try { await vpCancelRun(shortId); await refresh(shortId); }
    catch { /* ignore */ } finally { setCancelling(false); }
  }

  async function handleRegen(key: string, fn: () => Promise<void>) {
    setRegenLoading((p) => ({ ...p, [key]: true }));
    try { await fn(); await refresh(shortId!); }
    catch { /* ignore */ } finally {
      setRegenLoading((p) => ({ ...p, [key]: false }));
    }
  }

  async function handlePatchScene(sceneId: number, field: "image_prompt" | "video_prompt", value: string) {
    await vpPatchScene(shortId!, sceneId, { [field]: value });
    await refresh(shortId!);
  }

  const sceneRunning = (status: string) => RUNNING.has(status);

  return (
    <div className="vp-page vp2-page">
      <div className="vp2-card">

        {/* ── Header ── */}
        <div className="vp2-header">
          <div className="vp2-header__row1">
            <span className="vp2-header__run-id">{run.short_id}</span>
            <a href={vpDownloadAllUrl(run.short_id)} download className="vp2-header__zip">
              ⤓ Tải tất cả .zip
            </a>
          </div>
          <div className="vp2-header__row2">
            <span className={`vp2-badge vp2-badge--${run.status}`}>{sl(run.status)}</span>
            {isRunning && (
              <button type="button" className="vp2-cancel-btn" disabled={cancelling} onClick={handleCancel}>
                {cancelling ? "Đang huỷ…" : "Huỷ"}
              </button>
            )}
          </div>
          <div className="vp2-progress">
            <div className="vp2-progress__label">
              <span>Tổng tiến độ</span>
              <span>{clips_done} / {clips_total} clip · {pct}%</span>
            </div>
            <div className="vp2-progress__track">
              <div className="vp2-progress__bar" style={{ width: `${pct}%` }} />
            </div>
          </div>
        </div>

        {/* ── Products ── */}
        <div className="vp2-body">
          {run.products.map((p) => (
            <div key={p.id} className="vp2-product">
              <div className="vp2-product__heading">▸ Sản phẩm #{p.product_index + 1}</div>

              {p.videos.map((v) => (
                <div key={v.id} className={`vp2-video vp2-video--${v.status}`} data-testid={`video-${v.id}`}>

                  {/* Video header */}
                  <div className="vp2-video__header">
                    <span className="vp2-video__title">
                      Video {v.video_index + 1}
                      <span className={`vp2-video__status vp2-video__status--${v.status}`}>
                        · {sl(v.status)}
                      </span>
                    </span>
                  </div>

                  {/* Composite box */}
                  <div className="vp2-composite">
                    <Thumb mediaId={v.composite_media_id} aspect="9:16" placeholder="🧍" size="sm" />
                    <div className="vp2-composite__info">
                      <div className="vp2-composite__label">Ảnh gốc (composite)</div>
                      <div className="vp2-composite__desc">
                        Base image cho mọi storyboard của Video {v.video_index + 1}.
                      </div>
                    </div>
                  </div>

                  {/* Scenes */}
                  <div className="vp2-scenes">
                    {v.scenes.map((sc) => {
                      const busy = sceneRunning(sc.status);
                      return (
                        <div key={sc.id} className={`vp2-scene vp2-scene--${sc.status}`} data-testid={`scene-${sc.id}`}>
                          <Thumb mediaId={sc.storyboard_media_id} aspect="9:16" placeholder="storyboard" />
                          <Thumb mediaId={null} aspect="9:16" placeholder={sc.clip_media_id ? "▶" : "⏳"} />

                          <div className="vp2-scene__content">
                            <div className="vp2-scene__title">
                              Scene {sc.scene_index + 1}
                              <span className={`vp2-scene__dot vp2-scene__dot--${sc.status}${busy ? " vp2-scene__dot--anim" : ""}`} />
                            </div>

                            {/* Regen buttons */}
                            <div className="vp2-scene__regen-row">
                              <button
                                type="button"
                                className="vp2-regen-btn"
                                disabled={busy || !!regenLoading[`sb-${sc.id}`]}
                                onClick={() => handleRegen(`sb-${sc.id}`, () => vpRegenStoryboard(run.short_id, sc.id))}
                              >
                                {regenLoading[`sb-${sc.id}`] ? "…" : "↻ Storyboard"}
                              </button>
                              <button
                                type="button"
                                className="vp2-regen-btn"
                                disabled={busy || !!regenLoading[`cl-${sc.id}`] || !sc.storyboard_media_id}
                                onClick={() => handleRegen(`cl-${sc.id}`, () => vpRegenClip(run.short_id, sc.id))}
                              >
                                {regenLoading[`cl-${sc.id}`] ? "…" : "↻ Clip"}
                              </button>
                            </div>

                            {/* Editable prompts */}
                            {(sc.image_prompt || sc.video_prompt) && (
                              <>
                                <EditablePrompt
                                  label="IMAGE PROMPT"
                                  value={sc.image_prompt}
                                  disabled={busy}
                                  onSave={(v) => handlePatchScene(sc.id, "image_prompt", v)}
                                />
                                <EditablePrompt
                                  label="VIDEO PROMPT"
                                  value={sc.video_prompt}
                                  disabled={busy}
                                  onSave={(v) => handlePatchScene(sc.id, "video_prompt", v)}
                                />
                              </>
                            )}

                            {sc.error && <div className="vp2-scene__error">{sc.error}</div>}
                          </div>
                        </div>
                      );
                    })}
                  </div>

                  {/* Merged video */}
                  {v.merged_url && (
                    <div className="vp2-merged">
                      <video src={v.merged_url} controls />
                      <a href={vpVideoDownloadUrl(run.short_id, v.id)} download className="vp2-merged__dl">
                        ⤓ Download video
                      </a>
                    </div>
                  )}
                </div>
              ))}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
