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
