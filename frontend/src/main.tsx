import React from "react";
import ReactDOM from "react-dom/client";
import { HashRouter } from "react-router-dom";
import { App } from "./App";
import "@xyflow/react/dist/style.css";
import "./styles.css";

// HashRouter (not BrowserRouter): the packaged Electron app and the dev/prod
// server both load the SPA under the `/app/` base path
// (vite base "/app/", desktop/src/main.ts loadURL `…/app/`). The backend
// mounts the build via StaticFiles(html=True) at "/app" with NO SPA catch-all
// (agent/flowboard/main.py), so a hard reload / deep-link to a path route like
// `/app/video-pipeline/new` would 404 on disk. HashRouter keeps all route
// state after the `#`, so the server only ever sees `/app/` and reloads work
// everywhere with no backend changes.
ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <HashRouter>
      <App />
    </HashRouter>
  </React.StrictMode>,
);
