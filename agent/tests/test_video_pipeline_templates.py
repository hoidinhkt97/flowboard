import pytest

from flowboard.services.video_pipeline import templates


def test_create_and_list():
    t = templates.create_template(name="My", type_key="product_review",
                                  params={"scene_count": 4})
    assert t.id is not None
    rows = templates.list_templates()
    assert any(r.id == t.id for r in rows)


def test_update_template():
    t = templates.create_template(name="A", type_key="product_review", params={})
    updated = templates.update_template(t.id, name="B", params={"quality": "high"})
    assert updated.name == "B"
    assert updated.params["quality"] == "high"


def test_delete_template():
    t = templates.create_template(name="X", type_key="product_review", params={})
    templates.delete_template(t.id)
    assert all(r.id != t.id for r in templates.list_templates())


def test_builtin_cannot_be_modified_or_deleted():
    t = templates.create_template(name="Builtin", type_key="product_review",
                                  params={}, is_builtin=True)
    with pytest.raises(templates.TemplateProtectedError):
        templates.update_template(t.id, name="nope")
    with pytest.raises(templates.TemplateProtectedError):
        templates.delete_template(t.id)


def test_seed_builtins_idempotent():
    templates.seed_builtins()
    first = [r for r in templates.list_templates() if r.is_builtin]
    templates.seed_builtins()
    second = [r for r in templates.list_templates() if r.is_builtin]
    assert len(first) == len(second)
    assert len(first) >= 1


def test_update_missing_raises():
    with pytest.raises(templates.TemplateNotFoundError):
        templates.update_template(999999, name="ghost")
