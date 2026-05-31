def test_list_types(client):
    r = client.get("/api/video-pipeline/types")
    assert r.status_code == 200
    body = r.json()
    assert any(t["key"] == "product_review" for t in body)


def test_template_crud_flow(client):
    r = client.post("/api/video-pipeline/templates", json={
        "name": "T1", "type_key": "product_review", "params": {"scene_count": 3}})
    assert r.status_code == 201, r.text
    tid = r.json()["id"]

    r = client.get("/api/video-pipeline/templates")
    assert r.status_code == 200
    assert any(t["id"] == tid for t in r.json())

    r = client.patch(f"/api/video-pipeline/templates/{tid}",
                     json={"name": "T1-renamed"})
    assert r.status_code == 200
    assert r.json()["name"] == "T1-renamed"

    r = client.delete(f"/api/video-pipeline/templates/{tid}")
    assert r.status_code == 204


def test_builtin_template_protected(client):
    from flowboard.services.video_pipeline import templates
    t = templates.create_template(name="B", type_key="product_review",
                                  params={}, is_builtin=True)
    r = client.patch(f"/api/video-pipeline/templates/{t.id}", json={"name": "x"})
    assert r.status_code == 403
    r = client.delete(f"/api/video-pipeline/templates/{t.id}")
    assert r.status_code == 403


def test_patch_missing_template_404(client):
    r = client.patch("/api/video-pipeline/templates/987654", json={"name": "x"})
    assert r.status_code == 404
