import { useEffect, useRef } from "react";
import { Routes, Route } from "react-router-dom";
import { ReactFlowProvider } from "@xyflow/react";
import { Board } from "./canvas/Board";
import { AddNodePalette } from "./canvas/AddNodePalette";
import { StatusBar } from "./components/StatusBar";
import { Toolbar } from "./components/Toolbar";
// import { ChatSidebar } from "./components/ChatSidebar";
import { ProjectSidebar } from "./components/ProjectSidebar";
import { ReferencesPanel } from "./components/ReferencesPanel";
import { Toaster } from "./components/Toaster";
import { GenerationDialog } from "./components/GenerationDialog";
import { ResultViewer } from "./components/ResultViewer";
import { ForcedSetupGate } from "./components/ForcedSetupGate";
import { PipelineNewPage } from "./video-pipeline/pages/PipelineNewPage";
import { PipelineRunsPage } from "./video-pipeline/pages/PipelineRunsPage";
import { PipelineRunDetailPage } from "./video-pipeline/pages/PipelineRunDetailPage";
import { useBoardStore } from "./store/board";
import { useReferencesStore } from "./store/references";

// The original canvas (the `/` route). Markup is the exact ReactFlowProvider
// block that previously lived inline in App — relocated verbatim, no internal
// changes. The loading/boardId selectors move here with it since they only
// drive the canvas.
function CanvasWrap() {
  const loading = useBoardStore((s) => s.loading);
  const boardId = useBoardStore((s) => s.boardId);

  return (
    <ReactFlowProvider>
      <div className="canvas-wrap">
        <Toolbar />
        {loading && boardId === null ? (
          <div className="canvas-loading">Loading board…</div>
        ) : (
          <>
            <Board />
            <AddNodePalette />
          </>
        )}
        <StatusBar />
        <ReferencesPanel />
      </div>
    </ReactFlowProvider>
  );
}

export function App() {
  const loadInitialBoard = useBoardStore((s) => s.loadInitialBoard);
  const loadReferences = useReferencesStore((s) => s.load);
  const ran = useRef(false);

  useEffect(() => {
    if (ran.current) return;
    ran.current = true;
    loadInitialBoard();
    // Fire-and-forget: panel renders the loading state inline and the
    // app stays usable even if references fail to hydrate.
    void loadReferences();
  }, [loadInitialBoard, loadReferences]);

  return (
    <div className="app">
      <ProjectSidebar />
      <Routes>
        <Route path="/" element={<CanvasWrap />} />
        <Route path="/video-pipeline/new" element={<PipelineNewPage />} />
        <Route path="/video-pipeline/runs" element={<PipelineRunsPage />} />
        <Route
          path="/video-pipeline/runs/:shortId"
          element={<PipelineRunDetailPage />}
        />
      </Routes>
      {/* <ChatSidebar /> */}
      <Toaster />
      <GenerationDialog />
      <ResultViewer />
      <ForcedSetupGate />
    </div>
  );
}
