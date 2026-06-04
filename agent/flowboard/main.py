import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Header, Request as FastAPIRequest
from fastapi.middleware.cors import CORSMiddleware
from sqlmodel import select as _select_dt

from flowboard.db import get_session, init_db
from flowboard.db.models import DeviceToken, Request
from flowboard.routes import account_auth, account_settings, activity, auth, boards, chat, edges, ext_ws, extension, flow_projects, llm, media, nodes, plans, projects, prompt, upload, vision
from flowboard.routes import references as references_route
from flowboard.routes import requests as requests_route
from flowboard.services.registry import registry
from flowboard.services.security import hash_token
from flowboard.worker.processor import get_worker

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")


def _recover_orphan_running_requests() -> int:
    """Mark any pre-existing 'running' requests as failed so a restart doesn't
    leave nodes polling a request that nobody is processing anymore."""
    from datetime import datetime, timezone
    from sqlmodel import select as _select

    touched = 0
    with get_session() as s:
        rows = s.exec(_select(Request).where(Request.status == "running")).all()
        for r in rows:
            r.status = "failed"
            r.error = "agent_restart_lost"
            r.finished_at = datetime.now(timezone.utc)
            s.add(r)
            touched += 1
        if touched:
            s.commit()
    return touched


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    recovered = _recover_orphan_running_requests()
    if recovered:
        logger.info("recovered %d orphan running request(s) → failed", recovered)
    worker = get_worker()
    worker_task = asyncio.create_task(worker.start(), name="request-worker")
    logger.info("flowboard agent started (worker)")
    try:
        yield
    finally:
        worker.request_shutdown()
        try:
            await asyncio.wait_for(worker.drain(), timeout=5.0)
        except asyncio.TimeoutError:
            logger.warning("worker drain timed out")
        worker_task.cancel()
        await asyncio.gather(worker_task, return_exceptions=True)
        logger.info("flowboard agent stopped")


app = FastAPI(title="Flowboard Agent", version="0.0.2", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(boards.router)
app.include_router(nodes.router)
app.include_router(edges.router)
app.include_router(chat.router)
app.include_router(projects.router)
app.include_router(flow_projects.router)
app.include_router(references_route.router)
app.include_router(requests_route.router)
app.include_router(media.bytes_router)
app.include_router(media.api_router)
app.include_router(upload.router)
app.include_router(plans.router)
app.include_router(vision.router)
app.include_router(prompt.router)
app.include_router(auth.router)
app.include_router(account_auth.router)
app.include_router(account_settings.router)
app.include_router(extension.router)
app.include_router(ext_ws.router)
app.include_router(llm.router)
app.include_router(activity.router)


# Mount frontend static files if frontend/dist exists (desktop app deployment)
from pathlib import Path as _Path
import os as _os
from fastapi.staticfiles import StaticFiles as _StaticFiles

_frontend_dist = _os.getenv("FLOWBOARD_FRONTEND_DIST")
if _frontend_dist:
    _frontend_path = _Path(_frontend_dist)
else:
    _frontend_path = _Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"

if _frontend_path.exists() and (_frontend_path / "index.html").exists():
    app.mount("/app", _StaticFiles(directory=str(_frontend_path), html=True), name="frontend")
    logger.info("mounted frontend static files from %s", _frontend_path)
else:
    logger.info("frontend dist not found at %s (skipping static mount)", _frontend_path)


@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "online_accounts": len(registry._conns)}


@app.post("/api/ext/callback")
async def ext_callback(
    body: FastAPIRequest,
    x_device_token: str | None = Header(default=None, alias="X-Device-Token"),
) -> dict:
    if not x_device_token:
        raise HTTPException(status_code=401, detail="missing device token")
    with get_session() as s:
        row = s.exec(
            _select_dt(DeviceToken).where(DeviceToken.token_hash == hash_token(x_device_token))
        ).first()
        if row is None or row.revoked_at is not None:
            raise HTTPException(status_code=401, detail="invalid device token")
        account_id = row.account_id
    try:
        payload = await body.json()
    except Exception:
        raise HTTPException(status_code=400, detail="invalid json body")
    if not isinstance(payload, dict) or "id" not in payload:
        raise HTTPException(status_code=400, detail="missing id")
    fc = registry.get(account_id)
    matched = fc.resolve_callback(payload) if fc is not None else False
    return {"ok": matched}
