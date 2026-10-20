"""SQLite persistence for jobs.

A single table tracks every job's lifecycle. The connection is created per
call with a short timeout; SQLite handles the low write volume of a
single-worker queue comfortably.
"""
from __future__ import annotations

import json
import sqlite3
import time
from typing import Any, Optional

from .config import DB_PATH

# Job status values used across the app.
STATUS_QUEUED = "queued"
STATUS_RUNNING = "running"
STATUS_DONE = "done"
STATUS_ERROR = "error"


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    return conn


def init_db() -> None:
    """Create tables if they do not exist. Safe to call on every startup."""
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS jobs (
                id          TEXT PRIMARY KEY,
                file_id     TEXT NOT NULL,
                filename    TEXT NOT NULL,
                op          TEXT NOT NULL,
                params      TEXT NOT NULL DEFAULT '{}',
                status      TEXT NOT NULL DEFAULT 'queued',
                error       TEXT,
                result_path TEXT,
                created_at  REAL NOT NULL,
                updated_at  REAL NOT NULL
            )
            """
        )


def create_job(
    job_id: str,
    file_id: str,
    filename: str,
    op: str,
    params: dict[str, Any],
) -> None:
    now = time.time()
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO jobs (id, file_id, filename, op, params, status,
                              created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job_id,
                file_id,
                filename,
                op,
                json.dumps(params or {}),
                STATUS_QUEUED,
                now,
                now,
            ),
        )


def update_status(
    job_id: str,
    status: str,
    *,
    result_path: Optional[str] = None,
    error: Optional[str] = None,
) -> None:
    with _connect() as conn:
        conn.execute(
            """
            UPDATE jobs
               SET status = ?,
                   result_path = COALESCE(?, result_path),
                   error = COALESCE(?, error),
                   updated_at = ?
             WHERE id = ?
            """,
            (status, result_path, error, time.time(), job_id),
        )


def get_job(job_id: str) -> Optional[dict[str, Any]]:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    return _row_to_dict(row) if row else None


def list_jobs(limit: int = 100) -> list[dict[str, Any]]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    try:
        d["params"] = json.loads(d.get("params") or "{}")
    except (ValueError, TypeError):
        d["params"] = {}
    return d
