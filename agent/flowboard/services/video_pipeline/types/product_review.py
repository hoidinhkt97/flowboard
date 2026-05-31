from __future__ import annotations

from .base import Step


class ProductReviewType:
    key = "product_review"
    label = "Product Review"
    input_schema = {
        "character": {"required": True, "kind": "media", "label": "Nhân vật"},
        "products": {"required": True, "kind": "media_list", "min": 1, "label": "Sản phẩm"},
        "background": {"required": True, "kind": "media", "label": "Bối cảnh"},
        "script_brief": {"required": True, "kind": "text", "label": "Prompt kịch bản"},
    }

    def build_video_steps(self, ctx: dict) -> list[Step]:
        scene_count = int(ctx.get("scene_count", 3))
        steps: list[Step] = [
            Step("composite", "Ghép nhân vật + sản phẩm"),
            Step("script", "Sinh kịch bản"),
        ]
        for j in range(scene_count):
            steps.append(Step("storyboard", f"Storyboard scene {j}"))
            steps.append(Step("clip", f"Clip scene {j}"))
        steps.append(Step("merge", "Ghép video"))
        return steps
