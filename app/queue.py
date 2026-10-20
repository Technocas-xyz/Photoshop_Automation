"""Single-worker job queue with per-job log streaming.

Only one job runs at a time because there is exactly one logged-in Photoshop
session to share. Jobs are enqueued from the HTTP layer and drained by one
background worker task. Each job publishes timestamped log lines to an
asyncio pub/sub channel that the SSE endpoint subscribes to.
"""
from __future__ import annotations

import asyncio
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from . import db
from .config import (
    BLACKOUT_ENGINE,
    DEMO_MODE,
    JOB_TIMEOUT_SECONDS,
    RESULT_DIR,
    UPLOAD_DIR,
)
from . import imageops


# A log event delivered over SSE. `seq` is a monotonic per-job index used to
# de-duplicate between the replayed history and the live stream.
@dataclass
class LogEvent:
    level: str          # "info" | "success" | "error" | "status"
    message: str
    ts: float = field(default_factory=time.time)
    status: Optional[str] = None  # set for level == "status"
    seq: int = 0


# Sentinel pushed to subscribers when a job is fully finished.
_DONE = object()


class JobBus:
    """Per-job fan-out of log events to any number of SSE subscribers.

    Every event is tagged with a monotonic `seq`. A subscriber replays history
    first, then drains a live queue, yielding only events whose seq is greater
    than the last one it emitted. This makes the history→live handoff lossless
    and duplicate-free no matter when the client connects.
    """

    def __init__(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop
        self._history: list[LogEvent] = []
        self._subscribers: set[asyncio.Queue] = set()
        self._closed = False
        self._seq = 0

    # publish() and close() are called from the worker thread (run_in_executor),
    # so every mutation is marshaled back onto the event loop thread to keep the
    # history list and subscriber set race-free.
    def publish(self, event: LogEvent) -> None:
        self._loop.call_soon_threadsafe(self._publish_on_loop, event)

    def _publish_on_loop(self, event: LogEvent) -> None:
        self._seq += 1
        event.seq = self._seq
        self._history.append(event)
        for q in list(self._subscribers):
            q.put_nowait(event)

    def close(self) -> None:
        self._loop.call_soon_threadsafe(self._close_on_loop)

    def _close_on_loop(self) -> None:
        self._closed = True
        for q in list(self._subscribers):
            q.put_nowait(_DONE)

    async def subscribe(self):
        """Yield historical then live events until the job closes."""
        q: asyncio.Queue = asyncio.Queue()
        # Register before snapshotting history so nothing published during the
        # handoff is lost; the seq guard below drops any duplicates.
        self._subscribers.add(q)
        last_seq = 0
        try:
            for event in list(self._history):
                if event.seq > last_seq:
                    last_seq = event.seq
                    yield event
            if self._closed and q.empty():
                yield _DONE
                return
            while True:
                item = await q.get()
                if item is _DONE:
                    yield _DONE
                    return
                if item.seq > last_seq:
                    last_seq = item.seq
                    yield item
        finally:
            self._subscribers.discard(q)


class JobManager:
    """Owns the queue, the single worker, and the per-job buses."""

    def __init__(self) -> None:
        self._queue: asyncio.Queue[str] = asyncio.Queue()
        self._buses: dict[str, JobBus] = {}
        self._worker_task: Optional[asyncio.Task] = None

    # -- lifecycle ---------------------------------------------------------
    def start(self) -> None:
        if self._worker_task is None:
            self._worker_task = asyncio.create_task(self._worker_loop())

    async def stop(self) -> None:
        if self._worker_task:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
            self._worker_task = None

    # -- public API --------------------------------------------------------
    def bus_for(self, job_id: str) -> JobBus:
        bus = self._buses.get(job_id)
        if bus is None:
            bus = JobBus(asyncio.get_event_loop())
            self._buses[job_id] = bus
        return bus

    async def enqueue(self, job_id: str) -> None:
        # Ensure a bus exists so an immediate SSE subscribe works.
        self.bus_for(job_id)
        await self._queue.put(job_id)

    # -- worker ------------------------------------------------------------
    async def _worker_loop(self) -> None:
        while True:
            job_id = await self._queue.get()
            bus = self.bus_for(job_id)
            try:
                await asyncio.wait_for(
                    self._run_job(job_id, bus),
                    timeout=JOB_TIMEOUT_SECONDS,
                )
            except asyncio.TimeoutError:
                self._emit(
                    bus,
                    "error",
                    f"Job timed out after {JOB_TIMEOUT_SECONDS}s",
                )
                db.update_status(job_id, db.STATUS_ERROR, error="timeout")
                self._emit_status(bus, db.STATUS_ERROR)
            except Exception as exc:  # noqa: BLE001 - surface everything to log
                self._emit(bus, "error", f"Unexpected error: {exc}")
                self._emit(bus, "error", traceback.format_exc().splitlines()[-1])
                db.update_status(job_id, db.STATUS_ERROR, error=str(exc))
                self._emit_status(bus, db.STATUS_ERROR)
            finally:
                bus.close()
                self._queue.task_done()

    async def _run_job(self, job_id: str, bus: JobBus) -> None:
        job = db.get_job(job_id)
        if not job:
            self._emit(bus, "error", "Job record not found")
            return

        op = job["op"]
        params = job["params"]
        src = Path(job["file_id"])
        if not src.is_absolute():
            src = UPLOAD_DIR / job["file_id"]
        result_path = RESULT_DIR / f"{job_id}.png"

        db.update_status(job_id, db.STATUS_RUNNING)
        self._emit_status(bus, db.STATUS_RUNNING)
        self._emit(bus, "info", f"Starting '{op}' on {job['filename']}")

        use_photoshop = self._op_uses_photoshop(op) and not DEMO_MODE

        if DEMO_MODE:
            self._emit(bus, "info", "DEMO_MODE on — skipping Photoshop, using Pillow")

        if use_photoshop:
            await self._run_photoshop(job_id, op, src, result_path, params, bus)
        else:
            await self._run_pillow(op, src, result_path, params, bus)

        self._emit(bus, "success", "Processing completed successfully")
        db.update_status(job_id, db.STATUS_DONE, result_path=str(result_path))
        self._emit_status(bus, db.STATUS_DONE)
        self._emit(bus, "success", "Result downloaded and ready")

    def _op_uses_photoshop(self, op: str) -> bool:
        photoshop_ops = {"remove_background", "resolution", "color_adjustment"}
        if op == "blackout":
            return BLACKOUT_ENGINE == "photoshop"
        return op in photoshop_ops

    async def _run_pillow(self, op, src, result_path, params, bus: JobBus) -> None:
        self._emit(bus, "info", "Loading image into local pixel engine")
        loop = asyncio.get_running_loop()
        # Run CPU-bound work off the event loop.
        await loop.run_in_executor(
            None, imageops.run_pillow_op, op, str(src), str(result_path), params
        )
        self._emit(bus, "success", f"Applied '{op}' with Pillow/NumPy/OpenCV")

    async def _run_photoshop(self, job_id, op, src, result_path, params, bus: JobBus) -> None:
        # Imported lazily so the app still boots without Playwright installed
        # (e.g. pure DEMO_MODE environments).
        from .photoshop.session import PhotoshopSession
        from .photoshop.recipes import get_recipe

        recipe = get_recipe(op)
        if recipe is None:
            raise RuntimeError(f"No Photoshop recipe registered for op '{op}'")

        def log(level: str, message: str) -> None:
            self._emit(bus, level, message)

        self._emit(bus, "info", "Opening Photoshop Web in browser")
        loop = asyncio.get_running_loop()

        def _do() -> None:
            with PhotoshopSession(job_id=job_id, log=log) as session:
                session.open_image(str(src))
                recipe(session, params=params, log=log)
                session.export_png(str(result_path))

        await loop.run_in_executor(None, _do)

    # -- emit helpers ------------------------------------------------------
    def _emit(self, bus: JobBus, level: str, message: str) -> None:
        bus.publish(LogEvent(level=level, message=message))

    def _emit_status(self, bus: JobBus, status: str) -> None:
        bus.publish(LogEvent(level="status", message=status, status=status))


# Module-level singleton used by the FastAPI app.
manager = JobManager()
