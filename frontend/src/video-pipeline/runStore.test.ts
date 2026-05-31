import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { http, HttpResponse } from "msw";
import { server } from "../test/msw-server";
import { useRunStore } from "./runStore";

function makeRunDTO(short_id: string, status: string) {
  return {
    short_id, type_key: "product_review", flow_project_id: null,
    inputs: {}, status, error: null, cancelled: false,
    products: [], progress: { clips_total: status === "done" ? 1 : 0, clips_done: status === "done" ? 1 : 0 },
  };
}

beforeEach(() => { useRunStore.setState({ run: null, error: null, pollTimer: null }); });
afterEach(() => { useRunStore.getState().stop(); vi.clearAllTimers(); });

describe("runStore polling", () => {
  it("refreshOnce loads run", async () => {
    server.use(http.get("/api/video-pipeline/runs/vpr_x", () =>
      HttpResponse.json(makeRunDTO("vpr_x", "generating"))));
    await useRunStore.getState().refreshOnce("vpr_x");
    expect(useRunStore.getState().run?.status).toBe("generating");
  });

  it("refreshOnce sets error on network failure", async () => {
    server.use(http.get("/api/video-pipeline/runs/vpr_fail", () =>
      HttpResponse.error()));
    await useRunStore.getState().refreshOnce("vpr_fail");
    expect(useRunStore.getState().error).toBeTruthy();
  });

  it("stops polling on terminal status", async () => {
    server.use(http.get("/api/video-pipeline/runs/vpr_done", () =>
      HttpResponse.json(makeRunDTO("vpr_done", "done"))));
    useRunStore.getState().start("vpr_done");
    await vi.waitFor(() => expect(useRunStore.getState().run?.status).toBe("done"), { timeout: 3000 });
    expect(useRunStore.getState().pollTimer).toBeNull();
  });
});
