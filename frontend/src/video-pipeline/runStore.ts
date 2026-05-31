import { create } from "zustand";
import { vpGetRun, type VPRunDTO } from "../api/client";

const POLL_MS = 1500;
const TERMINAL = new Set(["done", "failed", "cancelled"]);

interface RunStoreState {
  run: VPRunDTO | null;
  error: string | null;
  pollTimer: ReturnType<typeof setTimeout> | null;
  start: (shortId: string) => void;
  stop: () => void;
  refreshOnce: (shortId: string) => Promise<void>;
}

export const useRunStore = create<RunStoreState>((set, get) => ({
  run: null,
  error: null,
  pollTimer: null,

  refreshOnce: async (shortId) => {
    try {
      const run = await vpGetRun(shortId);
      set({ run, error: null });
    } catch (e) {
      set({ error: e instanceof Error ? e.message : "poll failed" });
    }
  },

  start: (shortId) => {
    get().stop();
    const tick = async () => {
      await get().refreshOnce(shortId);
      const status = get().run?.status;
      if (status && TERMINAL.has(status)) {
        set({ pollTimer: null });
        return;
      }
      set({ pollTimer: setTimeout(tick, POLL_MS) });
    };
    void tick();
  },

  stop: () => {
    const t = get().pollTimer;
    if (t) clearTimeout(t);
    set({ pollTimer: null });
  },
}));
