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
      // ensureProjectId() resolves to `string | null` — null when no board is
      // loaded or project bootstrap failed. Guard before passing to uploadImage,
      // which requires a string projectId (mirrors NodeCard.tsx's pattern).
      const projectId = await useGenerationStore.getState().ensureProjectId();
      if (!projectId) { setError("no project"); return; }
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
      if (!projectId) { setError("no project"); return; }
      const out = await vpResolveInput({
        kind, source: "ai_gen", description: prompt,
        project_id: projectId, aspect_ratio: aspectRatio, variant_count: 4,
      });
      const entries = out.media_entries ?? [];
      setVariants(entries);
      if (entries.length > 0) {
        onChange({ source: tab, media_id: entries[0].media_id, prompt });
      }
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
