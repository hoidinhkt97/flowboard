from __future__ import annotations

from .base import PipelineType
from .product_review import ProductReviewType

REGISTRY: dict[str, PipelineType] = {
    ProductReviewType.key: ProductReviewType(),
}


def get(key: str) -> PipelineType:
    if key not in REGISTRY:
        raise KeyError(key)
    return REGISTRY[key]


def list_types() -> list[dict]:
    return [
        {"key": t.key, "label": t.label, "input_schema": t.input_schema}
        for t in REGISTRY.values()
    ]
