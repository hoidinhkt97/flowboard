import { useEffect, useRef, useState } from "react";
import { ReactFlowProvider } from "@xyflow/react";
import { Board } from "./canvas/Board";
import { AddNodePalette } from "./canvas/AddNodePalette";
import { StatusBar } from "./components/StatusBar";
import { Toolbar } from "./components/Toolbar";
import { ProjectSidebar } from "./components/ProjectSidebar";
import { ReferencesPanel } from "./components/ReferencesPanel";
import { Toaster } from "./components/Toaster";
import { GenerationDialog } from "./components/GenerationDialog";
import { ResultViewer } from "./components/ResultViewer";
import { ForcedSetupGate } from "./components/ForcedSetupGate";
import { LoginPage } from "./components/auth/LoginPage";
import { RegisterPage } from "./components/auth/RegisterPage";
import { useBoardStore } from "./store/board";
import { useReferencesStore } from "./store/references";
import { useAuthStore } from "./store/auth";

type AuthView = "login" | "register";

export function App() {
  const { token, account, initialized, initialize } = useAuthStore();
  const loadInitialBoard = useBoardStore((s) => s.loadInitialBoard);
  const loadReferences = useReferencesStore((s) => s.load);
  const loading = useBoardStore((s) => s.loading);
  const boardId = useBoardStore((s) => s.boardId);
  const ran = useRef(false);
  const [authView, setAuthView] = useState<AuthView>("login");

  useEffect(() => {
    void initialize();
  }, [initialize]);

  useEffect(() => {
    if (!token) return;
    if (ran.current) return;
    ran.current = true;
    loadInitialBoard();
    void loadReferences();
  }, [token, loadInitialBoard, loadReferences]);

  if (!initialized) {
    return (
      <div style={{ minHeight: "100vh", background: "#0b1326", display: "flex", alignItems: "center", justifyContent: "center" }}>
        <div style={{ color: "#ccc3d8", fontSize: "14px", fontFamily: "system-ui" }}>Loading…</div>
      </div>
    );
  }

  if (!token || !account) {
    if (authView === "register") {
      return <RegisterPage onGoLogin={() => setAuthView("login")} />;
    }
    return <LoginPage onGoRegister={() => setAuthView("register")} />;
  }

  return (
    <div className="app">
      <ProjectSidebar />
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
      <Toaster />
      <GenerationDialog />
      <ResultViewer />
      <ForcedSetupGate />
    </div>
  );
}
