import { describe, it, expect, beforeEach } from "vitest";
import { useWizardStore, wizardToInputs } from "./store";

beforeEach(() => useWizardStore.getState().reset());

describe("wizard store", () => {
  it("starts invalid (no media)", () => {
    expect(useWizardStore.getState().isValid()).toBe(false);
  });

  it("becomes valid when all inputs + brief present", () => {
    const s = useWizardStore.getState();
    s.setCharacter({ source: "upload", media_id: "c" });
    s.setBackground({ source: "upload", media_id: "b" });
    s.setProduct(0, { source: "upload", media_id: "p0" });
    s.setField("scriptBrief", "demo");
    expect(useWizardStore.getState().isValid()).toBe(true);
  });

  it("invalid if a product lacks media", () => {
    const s = useWizardStore.getState();
    s.setCharacter({ source: "upload", media_id: "c" });
    s.setBackground({ source: "upload", media_id: "b" });
    s.setField("scriptBrief", "demo");
    s.addProduct();
    s.setProduct(0, { source: "upload", media_id: "p0" });
    expect(useWizardStore.getState().isValid()).toBe(false);
  });

  it("add/remove product", () => {
    const s = useWizardStore.getState();
    s.addProduct();
    expect(useWizardStore.getState().products.length).toBe(2);
    s.removeProduct(1);
    expect(useWizardStore.getState().products.length).toBe(1);
  });

  it("loadTemplateParams maps snake_case", () => {
    useWizardStore.getState().loadTemplateParams({
      aspect_ratio: "16:9", scene_count: 5, video_count: 3,
    });
    const s = useWizardStore.getState();
    expect(s.aspectRatio).toBe("16:9");
    expect(s.sceneCount).toBe(5);
    expect(s.videoCount).toBe(3);
  });

  it("wizardToInputs produces snake_case payload", () => {
    const s = useWizardStore.getState();
    s.setCharacter({ source: "upload", media_id: "c" });
    s.setBackground({ source: "upload", media_id: "b" });
    s.setProduct(0, { source: "upload", media_id: "p0" });
    s.setField("scriptBrief", "demo");
    const inputs = wizardToInputs(useWizardStore.getState());
    expect(inputs.script_brief).toBe("demo");
    expect((inputs.products as unknown[]).length).toBe(1);
    expect(inputs.video_count).toBeDefined();
  });
});
