import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useWizardStore, wizardToInputs, type WizardState } from "../store";
import { InputCard } from "../components/InputCard";
import {
  vpCreateRun,
  vpStartRun,
  vpListTemplates,
  vpCreateTemplate,
  type VPTemplateDTO,
} from "../../api/client";

const ASPECT_RATIOS: WizardState["aspectRatio"][] = ["9:16", "1:1", "16:9"];
const SCENE_COUNTS = [2, 3, 4, 5];
const QUALITIES: { value: WizardState["quality"]; label: string }[] = [
  { value: "fast", label: "Nhanh" },
  { value: "standard", label: "Chuẩn" },
  { value: "high", label: "Cao" },
];
const CROSSFADES = [0, 0.4, 0.8];
const VIDEO_COUNTS = [1, 2, 3, 4];

export function PipelineNewPage() {
  const navigate = useNavigate();
  const s = useWizardStore();
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Template picker (minimal inline list — full modal deferred to Phase 7).
  const [templates, setTemplates] = useState<VPTemplateDTO[]>([]);
  const [showTemplates, setShowTemplates] = useState(false);
  const [templatesError, setTemplatesError] = useState<string | null>(null);

  // Save-template inline name input.
  const [templateName, setTemplateName] = useState("");
  const [savingTemplate, setSavingTemplate] = useState(false);
  const [saveMsg, setSaveMsg] = useState<string | null>(null);

  // Collapsible "Nâng cao" section.
  const [advancedOpen, setAdvancedOpen] = useState(false);

  useEffect(() => {
    if (!showTemplates) return;
    let cancelled = false;
    setTemplatesError(null);
    vpListTemplates()
      .then((list) => {
        if (!cancelled) setTemplates(list);
      })
      .catch((e) => {
        if (!cancelled)
          setTemplatesError(e instanceof Error ? e.message : "Không tải được template");
      });
    return () => {
      cancelled = true;
    };
  }, [showTemplates]);

  function paramsFromStore(): Record<string, unknown> {
    return {
      aspect_ratio: s.aspectRatio,
      scene_count: s.sceneCount,
      quality: s.quality,
      crossfade_sec: s.crossfadeSec,
      audio_enabled: s.audioEnabled,
      video_count: s.videoCount,
      concurrency_cap: s.concurrencyCap,
      script_brief: s.scriptBrief,
    };
  }

  async function handleStart() {
    if (!s.isValid()) {
      setError("Vui lòng điền đủ nhân vật, ≥1 sản phẩm, bối cảnh, prompt kịch bản.");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      const run = await vpCreateRun({ type_key: s.typeKey, inputs: wizardToInputs(s) });
      await vpStartRun(run.short_id);
      navigate(`/video-pipeline/runs/${run.short_id}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Tạo run thất bại");
    } finally {
      setSubmitting(false);
    }
  }

  async function handleSaveTemplate() {
    const name = templateName.trim() || "Template không tên";
    setSavingTemplate(true);
    setSaveMsg(null);
    try {
      await vpCreateTemplate({ name, type_key: s.typeKey, params: paramsFromStore() });
      setSaveMsg(`Đã lưu template "${name}".`);
      setTemplateName("");
    } catch (e) {
      setSaveMsg(e instanceof Error ? e.message : "Lưu template thất bại");
    } finally {
      setSavingTemplate(false);
    }
  }

  function applyTemplate(t: VPTemplateDTO) {
    useWizardStore.getState().loadTemplateParams(t.params);
    setShowTemplates(false);
  }

  const startDisabled = submitting || !s.isValid();

  return (
    <div className="vp-page vp-wizard" data-testid="vp-new-page">
      {/* 1. Header */}
      <header className="vp-wizard__header">
        <h1 className="vp-wizard__title">Tạo Video Pipeline</h1>
        <button
          type="button"
          className="vp-wizard__template-btn"
          onClick={() => setShowTemplates((v) => !v)}
        >
          📂 Tải template
        </button>
      </header>

      {showTemplates && (
        <div className="vp-wizard__template-picker" data-testid="vp-template-picker">
          {templatesError && (
            <div className="vp-wizard__error" role="alert">
              {templatesError}
            </div>
          )}
          {!templatesError && templates.length === 0 && (
            <div className="vp-wizard__hint">Chưa có template nào.</div>
          )}
          {templates.map((t) => (
            <button
              key={t.id}
              type="button"
              className="vp-wizard__template-item"
              onClick={() => applyTemplate(t)}
            >
              {t.name}
            </button>
          ))}
        </div>
      )}

      {/* 2. Loại pipeline */}
      <section className="vp-wizard__section">
        <label className="vp-wizard__section-title" htmlFor="vp-type">
          Loại pipeline
        </label>
        <select
          id="vp-type"
          className="vp-wizard__select"
          value={s.typeKey}
          onChange={(e) => s.setField("typeKey", e.target.value)}
        >
          <option value="product_review">Product Review</option>
        </select>
      </section>

      {/* 3. Nhân vật */}
      <section className="vp-wizard__section">
        <InputCard
          label="Nhân vật"
          kind="character"
          value={s.character}
          aspectRatio={s.aspectRatio}
          onChange={s.setCharacter}
        />
      </section>

      {/* 4. Sản phẩm (nhiều) */}
      <section className="vp-wizard__section">
        <div className="vp-wizard__section-title">Sản phẩm</div>
        <div className="vp-wizard__products">
          {s.products.map((p, i) => (
            <div className="vp-wizard__product" key={p.uid}>
              <InputCard
                label={`Sản phẩm ${i + 1}`}
                kind="product"
                value={p}
                aspectRatio={s.aspectRatio}
                onChange={(v) => s.setProduct(i, v)}
              />
              <button
                type="button"
                className="vp-wizard__remove-product"
                disabled={s.products.length <= 1}
                onClick={() => s.removeProduct(i)}
              >
                Xóa
              </button>
            </div>
          ))}
        </div>
        <button
          type="button"
          className="vp-wizard__add-product"
          onClick={() => s.addProduct()}
        >
          + Thêm sản phẩm
        </button>
      </section>

      {/* 5. Bối cảnh */}
      <section className="vp-wizard__section">
        <InputCard
          label="Bối cảnh"
          kind="background"
          value={s.background}
          aspectRatio={s.aspectRatio}
          onChange={s.setBackground}
        />
      </section>

      {/* 6. Prompt kịch bản */}
      <section className="vp-wizard__section">
        <label className="vp-wizard__section-title" htmlFor="vp-script">
          Prompt kịch bản
        </label>
        <textarea
          id="vp-script"
          className="vp-wizard__textarea"
          value={s.scriptBrief}
          placeholder="Mô tả nội dung / kịch bản video..."
          onChange={(e) => s.setField("scriptBrief", e.target.value)}
        />
      </section>

      {/* 7. Thông số video */}
      <section className="vp-wizard__section">
        <div className="vp-wizard__section-title">Thông số video</div>

        <div className="vp-wizard__field">
          <span className="vp-wizard__field-label">Tỉ lệ khung hình</span>
          <div className="vp-wizard__pills">
            {ASPECT_RATIOS.map((ar) => (
              <button
                key={ar}
                type="button"
                className={`vp-wizard__pill${s.aspectRatio === ar ? " vp-wizard__pill--active" : ""}`}
                onClick={() => s.setField("aspectRatio", ar)}
              >
                {ar}
              </button>
            ))}
          </div>
        </div>

        <div className="vp-wizard__field">
          <span className="vp-wizard__field-label">Số phân cảnh / video</span>
          <div className="vp-wizard__pills">
            {SCENE_COUNTS.map((n) => (
              <button
                key={n}
                type="button"
                className={`vp-wizard__pill${s.sceneCount === n ? " vp-wizard__pill--active" : ""}`}
                onClick={() => s.setField("sceneCount", n)}
              >
                {n}
              </button>
            ))}
          </div>
        </div>

        <div className="vp-wizard__field">
          <span className="vp-wizard__field-label">Chất lượng</span>
          <div className="vp-wizard__pills">
            {QUALITIES.map((q) => (
              <button
                key={q.value}
                type="button"
                className={`vp-wizard__pill${s.quality === q.value ? " vp-wizard__pill--active" : ""}`}
                onClick={() => s.setField("quality", q.value)}
              >
                {q.label}
              </button>
            ))}
          </div>
        </div>

        <div className="vp-wizard__field">
          <span className="vp-wizard__field-label">Chuyển cảnh (giây)</span>
          <div className="vp-wizard__pills">
            {CROSSFADES.map((c) => (
              <button
                key={c}
                type="button"
                className={`vp-wizard__pill${s.crossfadeSec === c ? " vp-wizard__pill--active" : ""}`}
                onClick={() => s.setField("crossfadeSec", c)}
              >
                {c}
              </button>
            ))}
          </div>
        </div>

        <div className="vp-wizard__field">
          <span className="vp-wizard__field-label">Audio</span>
          <button
            type="button"
            className={`vp-wizard__toggle${s.audioEnabled ? " vp-wizard__toggle--on" : ""}`}
            aria-pressed={s.audioEnabled}
            onClick={() => s.setField("audioEnabled", !s.audioEnabled)}
          >
            {s.audioEnabled ? "Bật" : "Tắt"}
          </button>
        </div>
      </section>

      {/* 8. Số video / sản phẩm */}
      <section className="vp-wizard__section">
        <div className="vp-wizard__section-title">Số video / sản phẩm</div>
        <div className="vp-wizard__pills">
          {VIDEO_COUNTS.map((n) => (
            <button
              key={n}
              type="button"
              className={`vp-wizard__pill${s.videoCount === n ? " vp-wizard__pill--active" : ""}`}
              onClick={() => s.setField("videoCount", n)}
            >
              {n}
            </button>
          ))}
        </div>
      </section>

      {/* 9. Nâng cao (collapsible) */}
      <section className="vp-wizard__section">
        <button
          type="button"
          className="vp-wizard__advanced-toggle"
          aria-expanded={advancedOpen}
          onClick={() => setAdvancedOpen((v) => !v)}
        >
          {advancedOpen ? "▾" : "▸"} Nâng cao
        </button>
        {advancedOpen && (
          <div className="vp-wizard__field">
            <label className="vp-wizard__field-label" htmlFor="vp-concurrency">
              Giới hạn song song (concurrency cap)
            </label>
            <input
              id="vp-concurrency"
              type="number"
              min={1}
              className="vp-wizard__number"
              value={s.concurrencyCap}
              onChange={(e) => s.setField("concurrencyCap", Number(e.target.value))}
            />
          </div>
        )}
      </section>

      {/* 10. Action row */}
      <div className="vp-wizard__actions">
        <div className="vp-wizard__save-template">
          <input
            type="text"
            className="vp-wizard__template-name"
            placeholder="Tên template"
            value={templateName}
            onChange={(e) => setTemplateName(e.target.value)}
          />
          <button
            type="button"
            className="vp-wizard__save-btn"
            disabled={savingTemplate}
            onClick={handleSaveTemplate}
          >
            {savingTemplate ? "Đang lưu..." : "💾 Lưu template"}
          </button>
        </div>
        <button
          type="button"
          className="vp-wizard__start-btn"
          disabled={startDisabled}
          onClick={handleStart}
          data-testid="vp-start-btn"
        >
          {submitting ? "Đang tạo..." : "▶ Bắt đầu"}
        </button>
      </div>

      {saveMsg && <div className="vp-wizard__hint">{saveMsg}</div>}
      {error && (
        <div className="vp-wizard__error" role="alert">
          {error}
        </div>
      )}
    </div>
  );
}
