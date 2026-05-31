import { create } from "zustand";

export type InputSource = "upload" | "gen" | "ai_gen";
export interface ResolvedInput { source: InputSource; media_id: string | null; prompt?: string; }

export interface WizardState {
  typeKey: string;
  character: ResolvedInput;
  background: ResolvedInput;
  products: ResolvedInput[];
  scriptBrief: string;
  aspectRatio: "9:16" | "1:1" | "16:9";
  sceneCount: number;
  quality: "fast" | "standard" | "high";
  crossfadeSec: number;
  audioEnabled: boolean;
  videoCount: number;
  concurrencyCap: number;
  setField: <K extends keyof WizardState>(key: K, value: WizardState[K]) => void;
  setCharacter: (v: ResolvedInput) => void;
  setBackground: (v: ResolvedInput) => void;
  addProduct: () => void;
  removeProduct: (index: number) => void;
  setProduct: (index: number, v: ResolvedInput) => void;
  loadTemplateParams: (params: Record<string, unknown>) => void;
  reset: () => void;
  isValid: () => boolean;
}

const EMPTY_INPUT: ResolvedInput = { source: "upload", media_id: null };
const INITIAL = {
  typeKey: "product_review",
  character: { ...EMPTY_INPUT },
  background: { ...EMPTY_INPUT },
  products: [{ ...EMPTY_INPUT }],
  scriptBrief: "",
  aspectRatio: "9:16" as const,
  sceneCount: 3,
  quality: "standard" as const,
  crossfadeSec: 0.4,
  audioEnabled: true,
  videoCount: 2,
  concurrencyCap: 4,
};

export const useWizardStore = create<WizardState>((set, get) => ({
  ...INITIAL,
  setField: (key, value) => set({ [key]: value } as Partial<WizardState>),
  setCharacter: (v) => set({ character: v }),
  setBackground: (v) => set({ background: v }),
  addProduct: () => set((s) => ({ products: [...s.products, { ...EMPTY_INPUT }] })),
  removeProduct: (index) => set((s) => ({ products: s.products.filter((_, i) => i !== index) })),
  setProduct: (index, v) => set((s) => ({ products: s.products.map((p, i) => (i === index ? v : p)) })),
  loadTemplateParams: (params) =>
    set({
      aspectRatio: (params.aspect_ratio as WizardState["aspectRatio"]) ?? get().aspectRatio,
      sceneCount: (params.scene_count as number) ?? get().sceneCount,
      quality: (params.quality as WizardState["quality"]) ?? get().quality,
      crossfadeSec: (params.crossfade_sec as number) ?? get().crossfadeSec,
      audioEnabled: (params.audio_enabled as boolean) ?? get().audioEnabled,
      videoCount: (params.video_count as number) ?? get().videoCount,
      concurrencyCap: (params.concurrency_cap as number) ?? get().concurrencyCap,
      scriptBrief: (params.script_brief as string) ?? get().scriptBrief,
    }),
  reset: () => set({ ...INITIAL, products: [{ ...EMPTY_INPUT }] }),
  isValid: () => {
    const s = get();
    const ok = (i: ResolvedInput) => !!i.media_id;
    return ok(s.character) && ok(s.background) &&
      s.products.length >= 1 && s.products.every(ok) &&
      s.scriptBrief.trim().length > 0;
  },
}));

export function wizardToInputs(s: WizardState): Record<string, unknown> {
  return {
    character: { source: s.character.source, media_id: s.character.media_id, prompt: s.character.prompt },
    background: { source: s.background.source, media_id: s.background.media_id, prompt: s.background.prompt },
    products: s.products.map((p) => ({ source: p.source, media_id: p.media_id, prompt: p.prompt })),
    script_brief: s.scriptBrief,
    aspect_ratio: s.aspectRatio,
    video_count: s.videoCount,
    scene_count: s.sceneCount,
    quality: s.quality,
    crossfade_sec: s.crossfadeSec,
    audio_enabled: s.audioEnabled,
    concurrency_cap: s.concurrencyCap,
  };
}
