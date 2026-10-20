"""FastAPI application: endpoints, static serving, and app lifecycle.

Routes:
  GET  /                     -> single-page UI
  POST /upload               -> save upload, return file_id + metadata
  POST /jobs                 -> enqueue a job, return job_id
  GET  /jobs/{id}/events     -> SSE stream of log lines + status
  GET  /results/{id}.png     -> processed PNG
  GET  /history              -> past jobs from SQLite
  GET  /photoshop/status     -> Chrome/Adobe connection + login state
"""
from __future__ import annotations

import json
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image

from . import db
import asyncio

from .config import (
    ALLOWED_EXT,
    BLACKOUT_ENGINE,
    DEMO_MODE,
    MAX_UPLOAD_BYTES,
    PS_CDP_URL,
    PS_CONNECT_MODE,
    RESULT_DIR,
    STATIC_DIR,
    UPLOAD_DIR,
)
from .queue import manager

# Operations the UI can request. "custom_edit" is a disabled placeholder.
VALID_OPS = {
    "blackout",
    "remove_background",
    "resolution",
    "ghost_pixel_removal",
    "transparent_pixel_cleanup",
    "semi_pixel_cleanup",
    "color_adjustment",
}


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    manager.start()
    try:
        yield
    finally:
        await manager.stop()


app = FastAPI(title="Design Studio Automation", lifespan=lifespan)


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
async def index() -> HTMLResponse:
    index_file = STATIC_DIR / "index.html"
    if not index_file.exists():
        return HTMLResponse("<h1>UI not found</h1>", status_code=500)
    return HTMLResponse(index_file.read_text(encoding="utf-8"))


@app.get("/config")
async def client_config() -> dict[str, Any]:
    """Expose a couple of flags the UI can show in a status pill."""
    return {
        "demo_mode": DEMO_MODE,
        "blackout_engine": BLACKOUT_ENGINE,
        "connect_mode": PS_CONNECT_MODE,
    }


@app.get("/photoshop/status")
async def photoshop_status() -> dict[str, Any]:
    """Report whether Chrome is reachable and logged in to Adobe.

    Shape: {connected, logged_in, window_size, url, demo_mode}.

    In DEMO_MODE we never touch Chrome — the pill just reflects demo state so
    the UI works with zero Chrome dependency. Otherwise we run the sync
    Playwright probe off the event loop in a worker thread.
    """
    if DEMO_MODE:
        return {
            "connected": False,
            "logged_in": False,
            "window_size": None,
            "url": None,
            "demo_mode": True,
        }

    # Import lazily so the app still boots without Playwright present.
    from .photoshop.session import probe_status

    loop = asyncio.get_running_loop()
    try:
        result = await loop.run_in_executor(None, probe_status, PS_CDP_URL)
    except Exception as exc:  # pragma: no cover - defensive
        result = {
            "connected": False,
            "logged_in": False,
            "window_size": None,
            "url": None,
            "error": str(exc),
        }
    result["demo_mode"] = False
    return result


# ---------------------------------------------------------------------------
# Upload
# ---------------------------------------------------------------------------
@app.post("/upload")
async def upload(file: UploadFile = File(...)) -> dict[str, Any]:
    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED_EXT:
        raise HTTPException(400, f"Unsupported file type '{ext}'. Use JPG/PNG/WEBP.")

    data = await file.read()
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            413, f"File too large ({len(data)} bytes). Max {MAX_UPLOAD_BYTES}."
        )
    if not data:
        raise HTTPException(400, "Empty file.")

    file_id = f"{uuid.uuid4().hex}{ext}"
    dest = UPLOAD_DIR / file_id
    dest.write_bytes(data)

    meta = _image_metadata(dest)
    return {
        "file_id": file_id,
        "filename": file.filename,
        "size": len(data),
        **meta,
    }


# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------
@app.post("/jobs")
async def create_job(payload: dict[str, Any]) -> dict[str, Any]:
    file_id = payload.get("file_id")
    op = payload.get("op")
    params = payload.get("params") or {}

    if not file_id:
        raise HTTPException(400, "Missing file_id.")
    if op not in VALID_OPS:
        raise HTTPException(400, f"Invalid or unsupported op '{op}'.")

    src = UPLOAD_DIR / file_id
    if not src.exists():
        raise HTTPException(404, "Uploaded file not found. Upload again.")

    original_name = payload.get("filename") or file_id
    job_id = uuid.uuid4().hex
    db.create_job(job_id, file_id, original_name, op, params)
    await manager.enqueue(job_id)
    return {"job_id": job_id, "status": db.STATUS_QUEUED}


@app.get("/jobs/{job_id}")
async def job_detail(job_id: str) -> dict[str, Any]:
    job = db.get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found.")
    return job


@app.get("/jobs/{job_id}/events")
async def job_events(job_id: str, request: Request) -> StreamingResponse:
    job = db.get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found.")
    bus = manager.bus_for(job_id)

    async def event_stream():
        from .queue import _DONE  # local import to access sentinel

        async for item in bus.subscribe():
            if await request.is_disconnected():
                break
            if item is _DONE:
                yield _sse({"type": "end"})
                break
            payload = {
                "type": item.level,
                "message": item.message,
                "ts": item.ts,
            }
            if item.status:
                payload["status"] = item.status
            yield _sse(payload)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ---------------------------------------------------------------------------
# Results & history
# ---------------------------------------------------------------------------
@app.get("/results/{job_id}.png")
async def result_png(job_id: str) -> FileResponse:
    path = RESULT_DIR / f"{job_id}.png"
    if not path.exists():
        raise HTTPException(404, "Result not ready.")
    return FileResponse(path, media_type="image/png", filename=f"{job_id}.png")


@app.get("/history")
async def history() -> list[dict[str, Any]]:
    jobs = db.list_jobs()
    out = []
    for j in jobs:
        out.append(
            {
                "id": j["id"],
                "filename": j["filename"],
                "op": j["op"],
                "status": j["status"],
                "time": j["created_at"],
                "result_path": f"/results/{j['id']}.png"
                if j["status"] == db.STATUS_DONE
                else None,
            }
        )
    return out


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _image_metadata(path: Path) -> dict[str, Any]:
    try:
        with Image.open(path) as im:
            return {
                "width": im.width,
                "height": im.height,
                "format": (im.format or path.suffix.lstrip(".")).upper(),
            }
    except Exception:
        return {"width": None, "height": None, "format": path.suffix.lstrip(".").upper()}


def _sse(data: dict[str, Any]) -> str:
    return f"data: {json.dumps(data)}\n\n"


# Static assets (css/js). Mounted last so routes above take priority.
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
