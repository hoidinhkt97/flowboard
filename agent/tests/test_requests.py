"""Tests for POST /api/requests and GET /api/requests/:id, plus the worker."""
import asyncio

import pytest

from flowboard.worker.processor import WorkerController


def _board(client, auth, name="T"):
    return client.post("/api/boards", json={"name": name}, headers=auth).json()


def test_create_request_persists_and_returns_row(client, auth):
    b = _board(client, auth)
    n = client.post("/api/nodes", json={"board_id": b["id"], "type": "image"}, headers=auth).json()

    r = client.post(
        "/api/requests",
        json={
            "node_id": n["id"],
            "type": "proxy",
            "params": {"url": "https://aisandbox-pa.googleapis.com/v1/ping"},
        },
    )
    assert r.status_code == 200
    row = r.json()
    assert row["type"] == "proxy"
    assert row["status"] == "queued"
    assert row["node_id"] == n["id"]
    assert "id" in row


def test_create_request_with_missing_node_returns_404(client):
    r = client.post(
        "/api/requests",
        json={"node_id": 9999, "type": "proxy", "params": {}},
    )
    assert r.status_code == 404


def test_get_request_returns_row(client):
    r = client.post(
        "/api/requests",
        json={"type": "proxy", "params": {"url": "https://aisandbox-pa.googleapis.com/v1/ping"}},
    ).json()
    r2 = client.get(f"/api/requests/{r['id']}")
    assert r2.status_code == 200
    assert r2.json()["id"] == r["id"]


def test_get_missing_request_returns_404(client):
    r = client.get("/api/requests/9999")
    assert r.status_code == 404


def test_cancel_queued_request_marks_canceled(client):
    r = client.post(
        "/api/requests",
        json={"type": "proxy", "params": {"url": "https://aisandbox-pa.googleapis.com/v1/ping"}},
    ).json()
    res = client.post(f"/api/requests/{r['id']}/cancel")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "canceled"
    assert body["error"] == "canceled"
    assert body["finished_at"] is not None


def test_cancel_missing_request_returns_404(client):
    res = client.post("/api/requests/9999/cancel")
    assert res.status_code == 404


def test_cancel_already_canceled_request_returns_409(client):
    r = client.post(
        "/api/requests",
        json={"type": "proxy", "params": {}},
    ).json()
    first = client.post(f"/api/requests/{r['id']}/cancel")
    assert first.status_code == 200
    again = client.post(f"/api/requests/{r['id']}/cancel")
    assert again.status_code == 409


@pytest.mark.asyncio
async def test_worker_skips_canceled_request(client):
    """If the user cancels a queued row before the worker pops it,
    the worker should not run the handler and not flip status away
    from the canceled state."""
    row = client.post(
        "/api/requests",
        json={"type": "proxy", "params": {"marker": "skip-me"}},
    ).json()
    # Cancel BEFORE enqueueing the rid so the row already reads
    # status='canceled' when the worker pops it.
    canceled = client.post(f"/api/requests/{row['id']}/cancel").json()
    assert canceled["status"] == "canceled"

    handler_calls: list[dict] = []

    async def _spy_handler(params):
        handler_calls.append(params)
        return ({"echo": params}, None)

    w = WorkerController(handlers={"proxy": _spy_handler})
    task = asyncio.create_task(w.start())
    try:
        w.enqueue(row["id"])
        # Give the worker a couple of ticks; if it were going to run,
        # it would do so well under a second.
        await asyncio.sleep(0.3)
        assert handler_calls == []
        current = client.get(f"/api/requests/{row['id']}").json()
        assert current["status"] == "canceled"
        assert current["error"] == "canceled"
    finally:
        w.request_shutdown()
        await asyncio.wait_for(task, timeout=2.0)


# ── Worker tests ──────────────────────────────────────────────────────────────


async def _ok_handler(params):
    return ({"echo": params}, None)


async def _fail_handler(_params):
    return ({}, "boom")


@pytest.mark.asyncio
async def test_worker_marks_request_done_on_ok(client):
    # Enqueue via the real API so we get a real DB row.
    row = client.post(
        "/api/requests",
        json={"type": "proxy", "params": {"marker": "abc"}},
    ).json()

    w = WorkerController(handlers={"proxy": _ok_handler})
    task = asyncio.create_task(w.start())
    try:
        w.enqueue(row["id"])
        # Poll the row until status flips, up to ~2s.
        for _ in range(40):
            await asyncio.sleep(0.05)
            current = client.get(f"/api/requests/{row['id']}").json()
            if current["status"] != "queued":
                break
        assert current["status"] == "done"
        # Worker injects __request_id alongside the user params (mirrors
        # the existing __node_id injection) so long-running handlers can
        # re-check the row for cancellation.
        assert current["result"]["echo"]["marker"] == "abc"
        assert current["result"]["echo"]["__request_id"] == row["id"]
        assert current["error"] is None
    finally:
        w.request_shutdown()
        await asyncio.wait_for(task, timeout=2.0)


@pytest.mark.asyncio
async def test_worker_marks_request_failed_on_error(client):
    row = client.post(
        "/api/requests", json={"type": "proxy", "params": {}}
    ).json()

    w = WorkerController(handlers={"proxy": _fail_handler})
    task = asyncio.create_task(w.start())
    try:
        w.enqueue(row["id"])
        for _ in range(40):
            await asyncio.sleep(0.05)
            current = client.get(f"/api/requests/{row['id']}").json()
            if current["status"] != "queued":
                break
        assert current["status"] == "failed"
        assert current["error"] == "boom"
    finally:
        w.request_shutdown()
        await asyncio.wait_for(task, timeout=2.0)


@pytest.mark.asyncio
async def test_worker_unknown_request_type_fails(client):
    row = client.post(
        "/api/requests", json={"type": "totally_made_up", "params": {}}
    ).json()
    w = WorkerController(handlers={"proxy": _ok_handler})
    task = asyncio.create_task(w.start())
    try:
        w.enqueue(row["id"])
        for _ in range(40):
            await asyncio.sleep(0.05)
            current = client.get(f"/api/requests/{row['id']}").json()
            if current["status"] != "queued":
                break
        assert current["status"] == "failed"
        assert "unknown_request_type" in current["error"]
    finally:
        w.request_shutdown()
        await asyncio.wait_for(task, timeout=2.0)


# ── create_project + gen_image handler tests ──────────────────────────────────


async def _poll_until_settled(client, rid, timeout_s=2.0):
    for _ in range(int(timeout_s / 0.05)):
        await asyncio.sleep(0.05)
        current = client.get(f"/api/requests/{rid}").json()
        if current["status"] not in ("queued", "running"):
            return current
    return current


@pytest.mark.asyncio
async def test_worker_create_project_stores_project_id(client):
    async def stub_create_project(params):
        assert params.get("name") == "Scene 01"
        return {"raw": {"status": 200}, "project_id": "proj-abc"}, None

    row = client.post(
        "/api/requests",
        json={"type": "create_project", "params": {"name": "Scene 01"}},
    ).json()

    w = WorkerController(handlers={"create_project": stub_create_project})
    task = asyncio.create_task(w.start())
    try:
        w.enqueue(row["id"])
        settled = await _poll_until_settled(client, row["id"])
        assert settled["status"] == "done"
        assert settled["result"]["project_id"] == "proj-abc"
    finally:
        w.request_shutdown()
        await asyncio.wait_for(task, timeout=2.0)


@pytest.mark.asyncio
async def test_worker_gen_image_stores_media_ids(client):
    async def stub_gen_image(params):
        assert params["prompt"] == "a cat"
        assert params["project_id"] == "proj-abc"
        return {"raw": {"status": 200}, "media_ids": ["m-1", "m-2"]}, None

    row = client.post(
        "/api/requests",
        json={
            "type": "gen_image",
            "params": {"prompt": "a cat", "project_id": "proj-abc"},
        },
    ).json()

    w = WorkerController(handlers={"gen_image": stub_gen_image})
    task = asyncio.create_task(w.start())
    try:
        w.enqueue(row["id"])
        settled = await _poll_until_settled(client, row["id"])
        assert settled["status"] == "done"
        assert settled["result"]["media_ids"] == ["m-1", "m-2"]
    finally:
        w.request_shutdown()
        await asyncio.wait_for(task, timeout=2.0)


# ── gen_video worker tests ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_worker_gen_video_happy_path(client, monkeypatch):
    """SDK returns op names then reports done on second poll; worker ingests."""
    from flowboard.worker import processor as proc

    # Speed up polls.
    monkeypatch.setattr(proc, "VIDEO_POLL_INTERVAL_S", 0.05)

    dispatch_called = {"n": 0}
    poll_calls = {"n": 0}

    class _StubSdk:
        async def gen_video(self, **kwargs):
            dispatch_called["n"] += 1
            assert kwargs["start_media_id"] == "src-1"
            return {"raw": {"ok": True}, "operation_names": ["op-1"]}

        async def check_async(self, names, workflows=None):
            poll_calls["n"] += 1
            if poll_calls["n"] == 1:
                return {
                    "raw": {},
                    "operations": [{"name": "op-1", "done": False, "media_entries": []}],
                }
            return {
                "raw": {},
                "operations": [
                    {
                        "name": "op-1",
                        "done": True,
                        "media_entries": [
                            {
                                "media_id": "vid-aaa",
                                "url": "https://flow-content.google/video/vid-aaa?sig=z",
                                "mediaType": "video",
                            }
                        ],
                    }
                ],
            }

    monkeypatch.setattr(proc, "get_flow_sdk", lambda fc=None: _StubSdk())

    row = client.post(
        "/api/requests",
        json={
            "type": "gen_video",
            "params": {
                "prompt": "ripple",
                "project_id": "abcd1234",
                "start_media_id": "src-1",
            },
        },
    ).json()

    w = WorkerController(handlers={"gen_video": proc._handle_gen_video})
    task = asyncio.create_task(w.start())
    try:
        w.enqueue(row["id"])
        for _ in range(200):
            await asyncio.sleep(0.05)
            current = client.get(f"/api/requests/{row['id']}").json()
            if current["status"] not in ("queued", "running"):
                break
        assert current["status"] == "done", current
        assert current["result"]["media_ids"] == ["vid-aaa"]
        assert dispatch_called["n"] == 1
        assert poll_calls["n"] >= 2
    finally:
        w.request_shutdown()
        await asyncio.wait_for(task, timeout=2.0)


@pytest.mark.asyncio
async def test_worker_gen_video_times_out(client, monkeypatch):
    from flowboard.worker import processor as proc

    monkeypatch.setattr(proc, "VIDEO_POLL_INTERVAL_S", 0.01)
    monkeypatch.setattr(proc, "VIDEO_POLL_MAX_CYCLES", 3)

    class _StubSdk:
        async def gen_video(self, **kwargs):
            return {"raw": {}, "operation_names": ["op-never"]}

        async def check_async(self, names, workflows=None):
            return {
                "raw": {},
                "operations": [{"name": "op-never", "done": False, "media_entries": []}],
            }

    monkeypatch.setattr(proc, "get_flow_sdk", lambda fc=None: _StubSdk())

    row = client.post(
        "/api/requests",
        json={
            "type": "gen_video",
            "params": {
                "prompt": "x",
                "project_id": "abcd1234",
                "start_media_id": "src",
            },
        },
    ).json()

    w = WorkerController(handlers={"gen_video": proc._handle_gen_video})
    task = asyncio.create_task(w.start())
    try:
        w.enqueue(row["id"])
        for _ in range(200):
            await asyncio.sleep(0.02)
            current = client.get(f"/api/requests/{row['id']}").json()
            if current["status"] not in ("queued", "running"):
                break
        assert current["status"] == "timeout"
        assert current["error"] == "timeout_waiting_video"
    finally:
        w.request_shutdown()
        await asyncio.wait_for(task, timeout=2.0)


@pytest.mark.asyncio
async def test_worker_gen_video_bails_on_per_op_error(client, monkeypatch):
    """When Flow returns ``operation.error.message`` (e.g. content filter),
    the worker must stamp the request `failed` immediately rather than
    polling for the full timeout."""
    from flowboard.worker import processor as proc

    monkeypatch.setattr(proc, "VIDEO_POLL_INTERVAL_S", 0.01)
    monkeypatch.setattr(proc, "VIDEO_POLL_MAX_CYCLES", 50)

    poll_count = {"n": 0}

    class _StubSdk:
        async def gen_video(self, **kwargs):
            return {"raw": {}, "operation_names": ["op-bad"]}

        async def check_async(self, names, workflows=None):
            poll_count["n"] += 1
            return {
                "raw": {},
                "operations": [
                    {
                        "name": "op-bad",
                        "done": True,
                        "media_entries": [],
                        "status": "MEDIA_GENERATION_STATUS_FAILED",
                        "error": "PUBLIC_ERROR_AUDIO_FILTERED",
                    }
                ],
            }

    monkeypatch.setattr(proc, "get_flow_sdk", lambda fc=None: _StubSdk())

    row = client.post(
        "/api/requests",
        json={
            "type": "gen_video",
            "params": {
                "prompt": "x",
                "project_id": "abcd1234",
                "start_media_id": "src",
            },
        },
    ).json()

    w = WorkerController(handlers={"gen_video": proc._handle_gen_video})
    task = asyncio.create_task(w.start())
    try:
        w.enqueue(row["id"])
        for _ in range(200):
            await asyncio.sleep(0.02)
            current = client.get(f"/api/requests/{row['id']}").json()
            if current["status"] not in ("queued", "running"):
                break
        assert current["status"] == "failed", current
        assert current["error"] == "PUBLIC_ERROR_AUDIO_FILTERED"
        assert poll_count["n"] == 1
    finally:
        w.request_shutdown()
        await asyncio.wait_for(task, timeout=2.0)


@pytest.mark.asyncio
async def test_worker_gen_video_partial_batch_keeps_succeeded(
    client, monkeypatch,
):
    from flowboard.worker import processor as proc

    monkeypatch.setattr(proc, "VIDEO_POLL_INTERVAL_S", 0.01)
    monkeypatch.setattr(proc, "VIDEO_POLL_MAX_CYCLES", 50)

    class _StubSdk:
        async def gen_video(self, **kwargs):
            return {
                "raw": {},
                "operation_names": ["op-a", "op-b-bad", "op-c", "op-d"],
            }

        async def check_async(self, names, workflows=None):
            return {
                "raw": {},
                "operations": [
                    {
                        "name": "op-a",
                        "done": True,
                        "media_entries": [
                            {
                                "media_id": "vid-a",
                                "url": "https://flow-content.google/v/a",
                                "mediaType": "video",
                            }
                        ],
                    },
                    {
                        "name": "op-b-bad",
                        "done": True,
                        "media_entries": [],
                        "error": "PUBLIC_ERROR_UNSAFE_GENERATION",
                    },
                    {
                        "name": "op-c",
                        "done": True,
                        "media_entries": [
                            {
                                "media_id": "vid-c",
                                "url": "https://flow-content.google/v/c",
                                "mediaType": "video",
                            }
                        ],
                    },
                    {
                        "name": "op-d",
                        "done": True,
                        "media_entries": [
                            {
                                "media_id": "vid-d",
                                "url": "https://flow-content.google/v/d",
                                "mediaType": "video",
                            }
                        ],
                    },
                ],
            }

    monkeypatch.setattr(proc, "get_flow_sdk", lambda fc=None: _StubSdk())

    row = client.post(
        "/api/requests",
        json={
            "type": "gen_video",
            "params": {
                "prompt": "x",
                "project_id": "abcd1234",
                "start_media_ids": ["src-a", "src-b", "src-c", "src-d"],
            },
        },
    ).json()

    w = WorkerController(handlers={"gen_video": proc._handle_gen_video})
    task = asyncio.create_task(w.start())
    try:
        w.enqueue(row["id"])
        for _ in range(200):
            await asyncio.sleep(0.02)
            current = client.get(f"/api/requests/{row['id']}").json()
            if current["status"] not in ("queued", "running"):
                break
        assert current["status"] == "done", current
        assert current.get("error") in (None, "")
        assert current["result"]["media_ids"] == [
            "vid-a", None, "vid-c", "vid-d",
        ]
        assert current["result"]["op_errors"] == {
            "op-b-bad": "PUBLIC_ERROR_UNSAFE_GENERATION",
        }
        assert current["result"]["slot_errors"] == [
            None, "PUBLIC_ERROR_UNSAFE_GENERATION", None, None,
        ]
        partial = current["result"]["partial_error"]
        assert "1/4 variants blocked" in partial
        assert "PUBLIC_ERROR_UNSAFE_GENERATION" in partial
    finally:
        w.request_shutdown()
        await asyncio.wait_for(task, timeout=2.0)


@pytest.mark.asyncio
async def test_worker_gen_video_dedupes_repeat_entries_across_polls(
    client, monkeypatch,
):
    from flowboard.worker import processor as proc

    monkeypatch.setattr(proc, "VIDEO_POLL_INTERVAL_S", 0.01)
    monkeypatch.setattr(proc, "VIDEO_POLL_MAX_CYCLES", 50)

    poll_state = {"n": 0}

    class _StubSdk:
        async def gen_video(self, **kwargs):
            return {"raw": {}, "operation_names": ["op-1", "op-2", "op-3"]}

        async def check_async(self, names, workflows=None):
            poll_state["n"] += 1
            n = poll_state["n"]
            ops = []
            for i, name in enumerate(["op-1", "op-2", "op-3"], start=1):
                done = i <= n
                entries = (
                    [{"media_id": f"vid-{i}", "url": f"https://flow-content.google/video/vid-{i}", "mediaType": "video"}]
                    if done
                    else []
                )
                ops.append({
                    "name": name,
                    "done": done,
                    "media_entries": entries,
                    "status": "MEDIA_GENERATION_STATUS_SUCCESSFUL" if done else "MEDIA_GENERATION_STATUS_PENDING",
                })
            return {"raw": {}, "operations": ops}

    monkeypatch.setattr(proc, "get_flow_sdk", lambda fc=None: _StubSdk())

    row = client.post(
        "/api/requests",
        json={
            "type": "gen_video",
            "params": {
                "prompt": "x",
                "project_id": "abcd1234",
                "start_media_id": "src",
            },
        },
    ).json()

    w = WorkerController(handlers={"gen_video": proc._handle_gen_video})
    task = asyncio.create_task(w.start())
    try:
        w.enqueue(row["id"])
        for _ in range(200):
            await asyncio.sleep(0.02)
            current = client.get(f"/api/requests/{row['id']}").json()
            if current["status"] not in ("queued", "running"):
                break
        assert current["status"] == "done", current
        media_ids = current["result"]["media_ids"]
        assert media_ids == ["vid-1", "vid-2", "vid-3"], media_ids
        assert len(media_ids) == len(set(media_ids))
    finally:
        w.request_shutdown()
        await asyncio.wait_for(task, timeout=2.0)


@pytest.mark.asyncio
async def test_cancel_running_video_bails_poll_and_keeps_canceled_status(
    client, monkeypatch,
):
    from flowboard.worker import processor as proc

    monkeypatch.setattr(proc, "VIDEO_POLL_INTERVAL_S", 0.05)
    monkeypatch.setattr(proc, "VIDEO_POLL_MAX_CYCLES", 50)

    poll_count = {"n": 0}

    class _StubSdk:
        async def gen_video(self, **kwargs):
            return {"raw": {}, "operation_names": ["op-x"]}

        async def check_async(self, names, workflows=None):
            poll_count["n"] += 1
            return {
                "raw": {},
                "operations": [
                    {"name": "op-x", "done": False, "media_entries": []}
                ],
            }

    monkeypatch.setattr(proc, "get_flow_sdk", lambda fc=None: _StubSdk())

    row = client.post(
        "/api/requests",
        json={
            "type": "gen_video",
            "params": {
                "prompt": "x",
                "project_id": "abcd1234",
                "start_media_id": "src",
            },
        },
    ).json()

    w = WorkerController(handlers={"gen_video": proc._handle_gen_video})
    task = asyncio.create_task(w.start())
    try:
        w.enqueue(row["id"])
        for _ in range(50):
            await asyncio.sleep(0.02)
            current = client.get(f"/api/requests/{row['id']}").json()
            if current["status"] == "running":
                break
        assert current["status"] == "running", current
        cancel_resp = client.post(f"/api/requests/{row['id']}/cancel")
        assert cancel_resp.status_code == 200
        assert cancel_resp.json()["status"] == "canceled"
        for _ in range(200):
            await asyncio.sleep(0.02)
            current = client.get(f"/api/requests/{row['id']}").json()
            if current["status"] == "canceled":
                break
        assert current["status"] == "canceled", current
        assert current["error"] == "canceled"
    finally:
        w.request_shutdown()
        await asyncio.wait_for(task, timeout=2.0)


@pytest.mark.asyncio
async def test_cancel_done_request_returns_409(client):
    """A request that already succeeded can't be canceled."""
    row = client.post(
        "/api/requests", json={"type": "proxy", "params": {}}
    ).json()

    async def _ok(_p):
        return ({"echo": True}, None)

    w = WorkerController(handlers={"proxy": _ok})
    task = asyncio.create_task(w.start())
    try:
        w.enqueue(row["id"])
        for _ in range(40):
            await asyncio.sleep(0.05)
            current = client.get(f"/api/requests/{row['id']}").json()
            if current["status"] == "done":
                break
        assert current["status"] == "done"
        res = client.post(f"/api/requests/{row['id']}/cancel")
        assert res.status_code == 409
    finally:
        w.request_shutdown()
        await asyncio.wait_for(task, timeout=2.0)


@pytest.mark.asyncio
async def test_worker_gen_video_rejects_missing_start(client):
    from flowboard.worker.processor import _handle_gen_video

    row = client.post(
        "/api/requests",
        json={"type": "gen_video", "params": {"prompt": "x", "project_id": "abcd1234"}},
    ).json()

    w = WorkerController(handlers={"gen_video": _handle_gen_video})
    task = asyncio.create_task(w.start())
    try:
        w.enqueue(row["id"])
        for _ in range(40):
            await asyncio.sleep(0.05)
            current = client.get(f"/api/requests/{row['id']}").json()
            if current["status"] not in ("queued", "running"):
                break
        assert current["status"] == "failed"
        assert current["error"] == "missing_start_media_id"
    finally:
        w.request_shutdown()
        await asyncio.wait_for(task, timeout=2.0)


@pytest.mark.asyncio
async def test_worker_gen_image_rejects_missing_prompt(client):
    row = client.post(
        "/api/requests",
        json={"type": "gen_image", "params": {"project_id": "p"}},
    ).json()

    from flowboard.worker.processor import _handle_gen_image

    w = WorkerController(handlers={"gen_image": _handle_gen_image})
    task = asyncio.create_task(w.start())
    try:
        w.enqueue(row["id"])
        settled = await _poll_until_settled(client, row["id"])
        assert settled["status"] == "failed"
        assert settled["error"] == "missing_prompt"
    finally:
        w.request_shutdown()
        await asyncio.wait_for(task, timeout=2.0)


def test_recover_orphan_running_requests_marks_them_failed(client):
    from datetime import datetime, timezone

    from flowboard.db import get_session
    from flowboard.db.models import Request
    from flowboard.main import _recover_orphan_running_requests

    with get_session() as s:
        s.add(Request(
            type="gen_video",
            status="running",
            params={},
            created_at=datetime.now(timezone.utc),
        ))
        s.add(Request(
            type="gen_image",
            status="running",
            params={},
            created_at=datetime.now(timezone.utc),
        ))
        s.add(Request(
            type="gen_image",
            status="failed",
            error="prior",
            params={},
            created_at=datetime.now(timezone.utc),
        ))
        s.commit()

    touched = _recover_orphan_running_requests()
    assert touched == 2

    rows = client.get("/api/requests").json() if False else None  # noqa: F841
    from sqlmodel import select as _select
    with get_session() as s:
        rows = s.exec(_select(Request)).all()
        statuses = sorted([(r.type, r.status, r.error) for r in rows])
    assert statuses == [
        ("gen_image", "failed", "agent_restart_lost"),
        ("gen_image", "failed", "prior"),
        ("gen_video", "failed", "agent_restart_lost"),
    ]

    assert _recover_orphan_running_requests() == 0


# ── Omni Flash r2v ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_worker_gen_video_omni_happy_path(client, monkeypatch):
    from flowboard.worker import processor as proc
    from flowboard.services import media_project_sync as sync_mod

    monkeypatch.setattr(proc, "VIDEO_POLL_INTERVAL_S", 0.05)

    async def _stub_sync(ids, project_id):
        return list(ids), []
    monkeypatch.setattr(sync_mod, "ensure_media_ids_in_project", _stub_sync)

    captured: dict = {}

    class _StubSdk:
        async def gen_video_omni(self, **kwargs):
            captured.update(kwargs)
            return {"raw": {"ok": True}, "operation_names": ["op-omni-1"]}

        async def check_async(self, names, workflows=None):
            return {
                "raw": {},
                "operations": [
                    {
                        "name": "op-omni-1",
                        "done": True,
                        "media_entries": [
                            {
                                "media_id": "omni-vid-aaa",
                                "url": "https://flow-content.google/video/omni-vid-aaa?sig=z",
                                "mediaType": "video",
                            }
                        ],
                    }
                ],
            }

    monkeypatch.setattr(proc, "get_flow_sdk", lambda fc=None: _StubSdk())

    row = client.post(
        "/api/requests",
        json={
            "type": "gen_video_omni",
            "params": {
                "prompt": "this girl smile",
                "project_id": "abcd1234",
                "ref_media_ids": ["ref-aaa"],
                "duration_s": 6,
                "aspect_ratio": "VIDEO_ASPECT_RATIO_PORTRAIT",
            },
        },
    ).json()

    w = WorkerController(handlers={"gen_video_omni": proc._handle_gen_video_omni})
    task = asyncio.create_task(w.start())
    try:
        w.enqueue(row["id"])
        for _ in range(60):
            await asyncio.sleep(0.05)
            current = client.get(f"/api/requests/{row['id']}").json()
            if current["status"] not in ("queued", "running"):
                break
        assert current["status"] == "done", current
        assert current["result"]["media_ids"] == ["omni-vid-aaa"]
        assert current["result"]["duration_s"] == 6
        assert captured["duration_s"] == 6
        assert captured["ref_media_ids"] == ["ref-aaa"]
        assert captured["aspect_ratio"] == "VIDEO_ASPECT_RATIO_PORTRAIT"
    finally:
        w.request_shutdown()
        await asyncio.wait_for(task, timeout=2.0)


@pytest.mark.asyncio
async def test_worker_gen_video_omni_rejects_invalid_duration(client, monkeypatch):
    from flowboard.worker import processor as proc

    class _StubSdk:
        async def gen_video_omni(self, **kwargs):
            raise AssertionError("must not dispatch with invalid duration")

    monkeypatch.setattr(proc, "get_flow_sdk", lambda fc=None: _StubSdk())

    out, err = await proc._handle_gen_video_omni(
        {
            "prompt": "test",
            "project_id": "abcd1234",
            "ref_media_ids": ["ref-1"],
            "duration_s": 5,
            "aspect_ratio": "VIDEO_ASPECT_RATIO_PORTRAIT",
            "paygate_tier": "PAYGATE_TIER_ONE",
        }
    )
    assert err == "invalid_duration_s"


@pytest.mark.asyncio
async def test_worker_gen_video_omni_requires_refs(client, monkeypatch):
    from flowboard.worker import processor as proc

    out, err = await proc._handle_gen_video_omni(
        {
            "prompt": "test",
            "project_id": "abcd1234",
            "ref_media_ids": [],
            "duration_s": 4,
            "aspect_ratio": "VIDEO_ASPECT_RATIO_PORTRAIT",
            "paygate_tier": "PAYGATE_TIER_ONE",
        }
    )
    assert err == "missing_ref_media_ids"


def test_omni_flash_credit_cost_table():
    from flowboard.services.flow_sdk import OMNI_FLASH_CREDIT_COST

    assert OMNI_FLASH_CREDIT_COST == {4: 15, 6: 20, 8: 25, 10: 30}


def test_omni_flash_resolve_model():
    from flowboard.services.flow_sdk import resolve_omni_flash_model

    assert resolve_omni_flash_model(4) == "abra_r2v_4s"
    assert resolve_omni_flash_model(6) == "abra_r2v_6s"
    assert resolve_omni_flash_model(8) == "abra_r2v_8s"
    assert resolve_omni_flash_model(10) == "abra_r2v_10s"
    import pytest as _pt
    with _pt.raises(ValueError, match="unsupported"):
        resolve_omni_flash_model(5)
