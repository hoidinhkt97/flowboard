import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { vpListRuns, type VPRunSummaryDTO } from "../../api/client";

const STATUS_VI: Record<string, string> = {
  pending: "Chờ", resolving: "Chuẩn bị", generating: "Đang tạo",
  merging: "Ghép video", done: "Hoàn thành", failed: "Thất bại", cancelled: "Đã huỷ",
};

const RESUME_STATUSES = new Set(["resolving", "generating", "merging"]);

function formatDate(iso: string) {
  const d = new Date(iso);
  return d.toLocaleDateString("vi-VN", { day: "2-digit", month: "2-digit", year: "numeric" })
    + " " + d.toLocaleTimeString("vi-VN", { hour: "2-digit", minute: "2-digit" });
}

export function PipelineRunsPage() {
  const navigate = useNavigate();
  const [runs, setRuns] = useState<VPRunSummaryDTO[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    vpListRuns()
      .then(setRuns)
      .catch((e) => setError(e instanceof Error ? e.message : "Không tải được danh sách"))
      .finally(() => setLoading(false));
  }, []);

  const interrupted = runs.filter((r) => RESUME_STATUSES.has(r.status) && !r.cancelled);

  return (
    <div className="vp-page vp-runs-list" data-testid="vp-runs-page">
      {/* Resume banner */}
      {interrupted.length > 0 && (
        <div className="vp-resume-banner">
          <span>⚡ {interrupted.length} run đang dở — chưa hoàn thành</span>
          <div className="vp-resume-banner__actions">
            {interrupted.map((r) => (
              <button
                key={r.short_id}
                type="button"
                className="vp-resume-banner__btn"
                onClick={() => navigate(`/video-pipeline/runs/${r.short_id}`)}
              >
                Tiếp tục {r.short_id}
              </button>
            ))}
          </div>
        </div>
      )}

      <div className="vp-runs-list__header">
        <h1 className="vp-runs-list__title">Danh sách Run</h1>
        <button
          type="button"
          className="vp-runs-list__new-btn"
          onClick={() => navigate("/video-pipeline/new")}
        >
          + Tạo mới
        </button>
      </div>

      {loading && <div className="vp-runs-list__hint">Đang tải…</div>}
      {error && <div className="vp-runs-list__error" role="alert">{error}</div>}
      {!loading && !error && runs.length === 0 && (
        <div className="vp-runs-list__empty">
          Chưa có run nào.{" "}
          <button type="button" className="vp-runs-list__link" onClick={() => navigate("/video-pipeline/new")}>
            Tạo run đầu tiên →
          </button>
        </div>
      )}

      {runs.length > 0 && (
        <div className="vp-runs-list__table">
          <div className="vp-runs-list__thead">
            <span>Run ID</span>
            <span>Trạng thái</span>
            <span>Tạo lúc</span>
            <span>Hoàn thành</span>
          </div>
          {runs.map((r) => (
            <button
              key={r.short_id}
              type="button"
              className={`vp-runs-list__row vp-runs-list__row--${r.status}`}
              onClick={() => navigate(`/video-pipeline/runs/${r.short_id}`)}
            >
              <span className="vp-runs-list__run-id">{r.short_id}</span>
              <span className={`vp-runs-list__badge vp-runs-list__badge--${r.status}`}>
                {STATUS_VI[r.status] ?? r.status}
              </span>
              <span className="vp-runs-list__date">{formatDate(r.created_at)}</span>
              <span className="vp-runs-list__date">
                {r.finished_at ? formatDate(r.finished_at) : "—"}
              </span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
