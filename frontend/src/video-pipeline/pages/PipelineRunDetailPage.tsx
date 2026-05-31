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
