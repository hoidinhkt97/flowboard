def _payload():
    return {
        "type_key": "product_review",
        "inputs": {
            "character": {"source": "upload", "media_id": "char_m"},
            "background": {"source": "upload", "media_id": "bg_m"},
            "products": [{"source": "upload", "media_id": "p0_m"}],
            "script_brief": "demo", "aspect_ratio": "9:16",
            "video_count": 1, "scene_count": 2,
        },
    }


def test_create_run_then_get_detail(client):
    r = client.post("/api/video-pipeline/runs", json=_payload())
    assert r.status_code == 201, r.text
    sid = r.json()["short_id"]

    r = client.get(f"/api/video-pipeline/runs/{sid}")
    assert r.status_code == 200
    dto = r.json()
    assert dto["status"] == "pending"
    assert len(dto["products"][0]["videos"][0]["scenes"]) == 2


def test_create_run_validation_error_returns_422(client):
    bad = _payload()
    bad["inputs"]["products"] = []
    r = client.post("/api/video-pipeline/runs", json=bad)
    assert r.status_code == 422


def test_get_missing_run_404(client):
    r = client.get("/api/video-pipeline/runs/vpr_nope")
    assert r.status_code == 404


def test_start_run_returns_202_and_sets_status(client):
    sid = client.post("/api/video-pipeline/runs", json=_payload()).json()["short_id"]
    r = client.post(f"/api/video-pipeline/runs/{sid}/start")
    assert r.status_code == 202
    dto = client.get(f"/api/video-pipeline/runs/{sid}").json()
    assert dto["status"] in ("resolving", "generating", "done")


def test_resolve_passthrough_upload(client):
    r = client.post("/api/video-pipeline/inputs/resolve", json={
        "kind": "character", "source": "upload", "media_id": "abc",
        "aspect_ratio": "9:16"})
    assert r.status_code == 200
    assert r.json()["media_id"] == "abc"
