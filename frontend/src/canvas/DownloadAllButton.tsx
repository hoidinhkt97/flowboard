import { useCallback, useEffect, useState } from "react";
import JSZip from "jszip";

import { mediaUrl } from "../api/client";
import { useBoardStore } from "../store/board";

/**
 * Downloads ALL media (images + videos) on the canvas.
 *
 * - 1 file → direct download
 * - 2+ files → fetch all, zip into a single .zip, download
 *
 * Uses a local mirror of node data to avoid circular deps with
 * useBoardStore that caused React error #185 in production builds.
 */
export function DownloadAllButton() {
  const nodes = useBoardStore((s) => s.nodes);
  const [mediaNodes, setMediaNodes] = useState<typeof nodes>([]);
  const [downloading, setDownloading] = useState(false);
  const [toast, setToast] = useState("");

  // Collect all downloadable nodes (image + video, not running/queued)
  useEffect(() => {
    setMediaNodes(
      nodes.filter(
        (n) =>
          ["image", "video"].includes(n.data.type) &&
          n.data.mediaId &&
          n.data.status !== "running" &&
          n.data.status !== "queued",
      ),
    );
  }, [nodes]);

  // Collect all media entries: each entry = { filename, fetchPromise }
  const collectEntries = useCallback(() => {
    const entries: { filename: string; fetchPromise: Promise<Blob> }[] = [];

    mediaNodes.forEach((node, idx) => {
      const mid = node.data.mediaId;
      if (!mid) return;

      const rawIds =
        node.data.mediaIds && node.data.mediaIds.length > 0
          ? node.data.mediaIds
          : [mid];
      const ids = rawIds.filter(
        (m): m is string => typeof m === "string" && m.length > 0,
      );

      const ext = node.data.type === "video" ? "mp4" : "png";

      ids.forEach((id, vi) => {
        const safeTitle = (node.data.title || node.data.type).replace(
          /[^A-Za-z0-9_-]+/g,
          "_",
        );
        const suffix = ids.length > 1 ? `-${vi + 1}` : "";
        const prefix = mediaNodes.length > 1 ? `${idx + 1}_` : "";
        const filename = `${prefix}${safeTitle}-${node.data.shortId || `m${idx + 1}`}${suffix}.${ext}`;

        entries.push({
          filename,
          fetchPromise: fetch(mediaUrl(id)).then((r) => r.blob()),
        });
      });
    });

    return entries;
  }, [mediaNodes]);

  const showToast = useCallback((msg: string) => {
    setToast(msg);
    setTimeout(() => setToast(""), 3000);
  }, []);

  const handleDownloadAll = useCallback(async () => {
    const entries = collectEntries();
    if (entries.length === 0) return;

    // Single file → direct download
    if (entries.length === 1) {
      showToast(`Đang tải ${entries[0].filename}…`);
      const blob = await entries[0].fetchPromise;
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = entries[0].filename;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
      showToast(`Đã tải xong!`);
      return;
    }

    // Multiple files → fetch all, zip, download
    setDownloading(true);
    showToast(`Đang tải và nén ${entries.length} file…`);
    try {
      const zip = new JSZip();
      const results = await Promise.allSettled(
        entries.map((e) =>
          e.fetchPromise.then((blob) => ({ filename: e.filename, blob })),
        ),
      );

      for (const r of results) {
        if (r.status === "fulfilled") {
          zip.file(r.value.filename, r.value.blob);
        }
      }

      const zipBlob = await zip.generateAsync({ type: "blob" });
      const url = URL.createObjectURL(zipBlob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `flowboard-media-${entries.length}.zip`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
      showToast(`Đã tải xong ${entries.length} file!`);
    } catch {
      showToast("Lỗi khi nén file, thử lại sau.");
    } finally {
      setDownloading(false);
    }
  }, [collectEntries, showToast]);

  if (mediaNodes.length === 0) return null;

  const count = mediaNodes.length;

  return (
    <>
      <button
        type="button"
        className="toolbar-dl-btn"
        onClick={handleDownloadAll}
        disabled={downloading}
        title={
          count === 1
            ? "Download media file"
            : `Download all ${count} media files as .zip`
        }
        style={{
          display: "flex",
          alignItems: "center",
          gap: 5,
          padding: "3px 10px",
          borderRadius: 6,
          border: "1px solid var(--border, #3a3f4b)",
          background: downloading
            ? "var(--bg-muted, #2a2e38)"
            : "var(--bg-panel, #1a1d24)",
          color: downloading
            ? "var(--text-muted, #8b8fa3)"
            : "var(--text, #e4e6eb)",
          fontSize: 12,
          fontWeight: 500,
          cursor: downloading ? "wait" : "pointer",
          whiteSpace: "nowrap",
          opacity: downloading ? 0.7 : 1,
        }}
      >
        <span style={{ fontSize: 13, lineHeight: 1, fontWeight: "bold" }}>
          {downloading ? "⟳" : "⬇"}
        </span>
        <span>
          {downloading ? "Đang nén…" : `Tải tất cả (${count})`}
        </span>
      </button>

      {/* Toast notification */}
      {toast && (
        <div
          style={{
            position: "fixed",
            top: 56,
            left: "50%",
            transform: "translateX(-50%)",
            padding: "8px 16px",
            borderRadius: 8,
            background: "var(--bg-panel, #1a1d24)",
            border: "1px solid var(--border, #3a3f4b)",
            color: "var(--text, #e4e6eb)",
            fontSize: 13,
            zIndex: 9999,
            boxShadow: "0 4px 12px rgba(0,0,0,0.4)",
            pointerEvents: "none",
          }}
        >
          {toast}
        </div>
      )}
    </>
  );
}
