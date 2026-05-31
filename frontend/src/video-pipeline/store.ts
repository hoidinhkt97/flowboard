import { create } from "zustand";

export type InputSource = "upload" | "gen" | "ai_gen";
export interface ResolvedInput { source: InputSource; media_id: string | null; prompt?: string; }
export interface ProductInput extends ResolvedInput { uid: string; }

let _pid = 0;
const nextUid = () => `p${_pid++}`;

export interface WizardState {
  typeKey: string;
  character: ResolvedInput;
  background: ResolvedInput;
  products: ProductInput[];
  scriptBrief: string;
  aspectRatio: "9:16" | "1:1" | "16:9";
  sceneCount: number;
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
  // setProduct receives a plain ResolvedInput from InputCard; the existing uid is preserved internally.
  loadTemplateParams: (params: Record<string, unknown>) => void;
  reset: () => void;
  isValid: () => boolean;
}

const EMPTY_INPUT: ResolvedInput = { source: "upload", media_id: null };
const INITIAL = {
  typeKey: "product_review",
  character: { ...EMPTY_INPUT },
  background: { ...EMPTY_INPUT },
  products: [{ ...EMPTY_INPUT, uid: nextUid() }],
  scriptBrief: "",
  aspectRatio: "9:16" as const,
  sceneCount: 3,
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
  addProduct: () => set((s) => ({ products: [...s.products, { ...EMPTY_INPUT, uid: nextUid() }] })),
  removeProduct: (index) => set((s) => ({ products: s.products.filter((_, i) => i !== index) })),
  setProduct: (index, v) =>
    set((s) => ({
      products: s.products.map((p, i) => (i === index ? { ...v, uid: s.products[index].uid } : p)),
    })),
  loadTemplateParams: (params) =>
    set({
      aspectRatio: (params.aspect_ratio as WizardState["aspectRatio"]) ?? get().aspectRatio,
      sceneCount: (params.scene_count as number) ?? get().sceneCount,
      crossfadeSec: (params.crossfade_sec as number) ?? get().crossfadeSec,
      audioEnabled: (params.audio_enabled as boolean) ?? get().audioEnabled,
      videoCount: (params.video_count as number) ?? get().videoCount,
      concurrencyCap: (params.concurrency_cap as number) ?? get().concurrencyCap,
      scriptBrief: (params.script_brief as string) ?? get().scriptBrief,
    }),
  reset: () => set({ ...INITIAL, products: [{ ...EMPTY_INPUT, uid: nextUid() }] }),
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
    crossfade_sec: s.crossfadeSec,
    audio_enabled: s.audioEnabled,
    concurrency_cap: s.concurrencyCap,
  };
}
