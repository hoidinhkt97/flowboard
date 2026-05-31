import pytest

from flowboard.routes import video_pipeline as vp_routes


def _payload():
    return {"type_key": "product_review", "inputs": {
        "character": {"source": "upload", "media_id": "c"},
        "background": {"source": "upload", "media_id": "b"},
        "products": [{"source": "upload", "media_id": "p0"}],
        "script_brief": "x", "aspect_ratio": "9:16",
        "video_count": 1, "scene_count": 1}}


def test_start_launches_orchestrator(client, monkeypatch):
    launched = {}

    async def fake_orchestrator_run(short_id, **k):
        launched["short_id"] = short_id

    monkeypatch.setattr(vp_routes, "_orchestrator_run", fake_orchestrator_run)

    sid = client.post("/api/video-pipeline/runs", json=_payload()).json()["short_id"]
    r = client.post(f"/api/video-pipeline/runs/{sid}/start")
    assert r.status_code == 202

    import asyncio, time
    for _ in range(50):
        if launched.get("short_id") == sid:
            break
        time.sleep(0.02)
    assert launched.get("short_id") == sid
